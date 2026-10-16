"""IRONMAN Coaching Radar V1: Prefect read-only pipeline.

Execution model:
- Prefect staging reads bounded TrainingPeaks data through the private VPC bridge.
- Deterministic rules build a triage report; no AI and no provider writes.
- Full input + report are persisted on Prefect staging.
- The report is posted back to the private result sink on ironman-tp-mcp so
  ChatGPT can read it through the MCP Coaching Radar tool.

Pilot scope is deliberately limited to Massimiliano Polverari (athlete 2932097).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from prefect import flow, task

PILOT_ATHLETE_ID = 2932097
DEFAULT_BRIDGE_BASE = "http://10.114.0.2:8787"
DEFAULT_OUTPUT_DIR = Path("/var/lib/ironman-prefect/radar")
ENDURANCE = {"Swim", "Bike", "Run", "Brick"}


def _window(as_of: str, lookback_days: int, lookahead_days: int) -> tuple[str, str]:
    day = date.fromisoformat(as_of)
    if not 1 <= lookback_days <= 14:
        raise ValueError("LOOKBACK_OUT_OF_RANGE")
    if not 1 <= lookahead_days <= 7:
        raise ValueError("LOOKAHEAD_OUT_OF_RANGE")
    return (
        (day - timedelta(days=lookback_days)).isoformat(),
        (day + timedelta(days=lookahead_days)).isoformat(),
    )


def _post_json(url: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP_{response.status}")
        return json.loads(response.read().decode("utf-8"))


def build_report(raw: dict[str, Any], as_of: str) -> dict[str, Any]:
    if raw.get("schema") != "IRONMAN_TP_RADAR_INPUT_V1":
        raise ValueError("RADAR_INPUT_SCHEMA_MISMATCH")
    if int(raw.get("athlete_id") or 0) != PILOT_ATHLETE_ID:
        raise ValueError("PILOT_ATHLETE_ID_MISMATCH")
    if raw.get("trainingpeaks_writes") != 0:
        raise ValueError("INPUT_WRITE_GUARD_FAILED")

    today = date.fromisoformat(as_of)
    details = {
        str(item.get("id")): item
        for item in raw.get("completed_details", [])
        if isinstance(item, dict) and item.get("id")
    }
    alerts: list[dict[str, Any]] = []
    upcoming: list[dict[str, Any]] = []
    missing_feedback: list[str] = []
    seen: set[str] = set()

    for workout in raw.get("workouts", []):
        wid = str(workout.get("id") or "")
        if not wid or wid in seen:
            raise ValueError("DUPLICATE_OR_MISSING_WORKOUT_ID")
        seen.add(wid)
        workout_day = date.fromisoformat(str(workout["date"]))
        sport = workout.get("sport")
        status = workout.get("type")

        if workout_day > today:
            if sport in ENDURANCE or sport == "Strength":
                upcoming.append({
                    "date": workout_day.isoformat(),
                    "workout_id": wid,
                    "sport": sport,
                    "title": workout.get("title", ""),
                    "status": status,
                })
            continue

        if sport not in ENDURANCE:
            continue

        if status == "completed":
            detail = details.get(wid) or {}
            metrics = detail.get("metrics") or {}
            planned_tss = metrics.get("tss_planned", workout.get("tss_planned"))
            actual_tss = metrics.get("tss_actual", workout.get("tss_actual"))
            planned_duration = metrics.get("duration_planned", workout.get("duration_planned"))
            actual_duration = metrics.get("duration_actual", workout.get("duration_actual"))
            planned_if = metrics.get("if_planned")
            actual_if = metrics.get("if_actual")
            rpe = detail.get("rpe")

            if isinstance(planned_tss, (int, float)) and planned_tss > 0 and isinstance(actual_tss, (int, float)):
                ratio = actual_tss / planned_tss
                if ratio >= 2.0:
                    alerts.append({
                        "severity": "YELLOW",
                        "category": "TSS_DATA_QUALITY",
                        "date": workout_day.isoformat(),
                        "workout_id": wid,
                        "sport": sport,
                        "planned_tss": round(planned_tss, 2),
                        "actual_tss": round(actual_tss, 2),
                        "ratio": round(ratio, 2),
                        "reason": "Discrepanza numerica: verificare soglie, sensori, IF e RPE; non inferire sovraccarico.",
                    })

            if (
                isinstance(actual_if, (int, float))
                and actual_if >= 1.20
                and isinstance(rpe, (int, float))
                and rpe <= 4
            ):
                alerts.append({
                    "severity": "YELLOW",
                    "category": "IF_DATA_QUALITY",
                    "date": workout_day.isoformat(),
                    "workout_id": wid,
                    "sport": sport,
                    "if_planned": planned_if,
                    "if_actual": round(actual_if, 3),
                    "rpe": rpe,
                    "reason": "IF molto alto rispetto a RPE basso/moderato: trattare prima come possibile problema di soglia o dato.",
                })

            if (
                isinstance(planned_duration, (int, float))
                and planned_duration > 0
                and isinstance(actual_duration, (int, float))
                and actual_duration / planned_duration < 0.75
            ):
                alerts.append({
                    "severity": "YELLOW",
                    "category": "DURATION_SHORT",
                    "date": workout_day.isoformat(),
                    "workout_id": wid,
                    "sport": sport,
                    "planned_minutes": round(planned_duration * 60, 1),
                    "actual_minutes": round(actual_duration * 60, 1),
                })

            if rpe is None:
                missing_feedback.append(wid)

        elif status == "planned" and workout_day < today:
            alerts.append({
                "severity": "YELLOW",
                "category": "COMPLETION_UNCONFIRMED",
                "date": workout_day.isoformat(),
                "workout_id": wid,
                "sport": sport,
                "reason": "Seduta senza eseguito associato; non dichiarare automaticamente saltata.",
            })

    metrics_count = int((raw.get("metrics") or {}).get("count") or 0)
    report: dict[str, Any] = {
        "schema": "IRONMAN_COACHING_RADAR_V1",
        "mode": "READ_ONLY",
        "athlete_id": PILOT_ATHLETE_ID,
        "as_of": as_of,
        "status": "YELLOW" if alerts else "GREEN",
        "review_required": bool(alerts),
        "alerts": sorted(alerts, key=lambda x: (x["date"], x["workout_id"], x["category"])),
        "upcoming": sorted(upcoming, key=lambda x: (x["date"], x["workout_id"])),
        "data_quality": {
            "wellness_metrics_count": metrics_count,
            "missing_rpe_workout_ids": sorted(missing_feedback),
            "note": (
                "Assenza di wellness/feedback non equivale a benessere o disponibilita' confermati."
            ),
        },
        "source": {
            "bridge_schema": raw.get("schema"),
            "bridge_fetched_at_utc": raw.get("fetched_at_utc"),
            "window_start": raw.get("start_date"),
            "window_end": raw.get("end_date"),
            "workout_count": len(raw.get("workouts", [])),
            "completed_detail_count": len(raw.get("completed_details", [])),
        },
        "trainingpeaks_writes": 0,
    }
    digest_input = json.dumps(report, sort_keys=True, separators=(",", ":")).encode("utf-8")
    report["evidence_sha256"] = hashlib.sha256(digest_input).hexdigest()
    return report


def persist_bundle(
    raw: dict[str, Any],
    report: dict[str, Any],
    output_dir: Path,
) -> dict[str, str]:
    athlete_id = str(report["athlete_id"])
    as_of = str(report["as_of"])
    target = output_dir / athlete_id
    target.mkdir(parents=True, exist_ok=True)
    os.chmod(target, 0o700)

    paths = {
        "input": target / f"input_{as_of}.json",
        "report": target / f"report_{as_of}.json",
        "latest": target / "latest.json",
    }
    for key, payload in (("input", raw), ("report", report), ("latest", report)):
        path = paths[key]
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target, delete=False) as tmp:
            json.dump(payload, tmp, indent=2, ensure_ascii=False)
            tmp.write("\n")
            temp_path = Path(tmp.name)
        os.chmod(temp_path, 0o600)
        temp_path.replace(path)
        os.chmod(path, 0o600)
    return {key: str(path) for key, path in paths.items()}


@task(name="fetch-trainingpeaks-radar-input", retries=2, retry_delay_seconds=10)
def fetch_radar_input(
    bridge_base: str,
    athlete_id: int,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    if athlete_id != PILOT_ATHLETE_ID:
        raise ValueError("PILOT_ATHLETE_ID_MISMATCH")
    return _post_json(
        bridge_base.rstrip("/") + "/v1/radar-input",
        {"athlete_id": str(athlete_id), "start_date": start_date, "end_date": end_date},
    )


@task(name="build-deterministic-radar", retries=0)
def build_radar_task(raw: dict[str, Any], as_of: str) -> dict[str, Any]:
    return build_report(raw, as_of)


@task(name="persist-radar-evidence", retries=1, retry_delay_seconds=2)
def persist_radar_task(
    raw: dict[str, Any],
    report: dict[str, Any],
    output_dir: str,
) -> dict[str, str]:
    return persist_bundle(raw, report, Path(output_dir))


@task(name="publish-radar-to-mcp-readback", retries=2, retry_delay_seconds=5)
def publish_radar_task(bridge_base: str, report: dict[str, Any]) -> dict[str, Any]:
    result = _post_json(bridge_base.rstrip("/") + "/v1/radar-result", report)
    if not result.get("stored") or result.get("trainingpeaks_writes") != 0:
        raise RuntimeError("RADAR_RESULT_SINK_READBACK_FAILED")
    return result


@flow(name="ironman-coaching-radar-v1", retries=0, log_prints=False)
def coaching_radar_flow(
    as_of: str,
    athlete_id: int = PILOT_ATHLETE_ID,
    lookback_days: int = 3,
    lookahead_days: int = 3,
    bridge_base: str = DEFAULT_BRIDGE_BASE,
    output_dir: str = str(DEFAULT_OUTPUT_DIR),
) -> dict[str, Any]:
    start_date, end_date = _window(as_of, lookback_days, lookahead_days)
    raw = fetch_radar_input(bridge_base, athlete_id, start_date, end_date)
    report = build_radar_task(raw, as_of)
    files = persist_radar_task(raw, report, output_dir)
    sink = publish_radar_task(bridge_base, report)
    return {
        "stage": "IRONMAN_COACHING_RADAR_V1_DONE",
        "athlete_id": athlete_id,
        "as_of": as_of,
        "status": report["status"],
        "alert_count": len(report["alerts"]),
        "evidence_sha256": report["evidence_sha256"],
        "files": files,
        "sink": sink,
        "trainingpeaks_writes": 0,
    }
