"""IRONMAN Coaching Radar V2: multi-athlete Prefect read-only pipeline.

- Reads only through the private TrainingPeaks bridge.
- One isolated report per athlete, plus one group summary.
- Runs athletes sequentially to keep load bounded on the TP droplet.
- No TrainingPeaks writes. No AI decisions. No calendar mutations.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from prefect import flow, task

DEFAULT_BRIDGE_BASE = "http://10.114.0.2:8787"
DEFAULT_OUTPUT_DIR = Path("/var/lib/ironman-prefect/radar")
ROSTER_PATH = Path(__file__).resolve().parents[2] / "data" / "coaching_radar_alberto_group_v1.json"
ENDURANCE = {"Swim", "Bike", "Run", "Brick"}
LOCAL_TZ = ZoneInfo("Europe/Rome")


def _today_local() -> str:
    return datetime.now(LOCAL_TZ).date().isoformat()


def _resolved_as_of(as_of: str | None) -> str:
    value = (as_of or "").strip()
    return date.fromisoformat(value).isoformat() if value else _today_local()


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


def _load_roster() -> dict[int, str]:
    raw = json.loads(ROSTER_PATH.read_text(encoding="utf-8"))
    if raw.get("schema") != "IRONMAN_COACHING_RADAR_ROSTER_V1":
        raise ValueError("ROSTER_SCHEMA_MISMATCH")
    roster: dict[int, str] = {}
    for item in raw.get("athletes", []):
        if not item.get("enabled"):
            continue
        athlete_id = int(item["athlete_id"])
        if athlete_id in roster:
            raise ValueError("DUPLICATE_ROSTER_ATHLETE")
        roster[athlete_id] = str(item["name"])
    if not roster:
        raise ValueError("EMPTY_ROSTER")
    return roster


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


def build_report(
    raw: dict[str, Any],
    as_of: str,
    expected_athlete_id: int,
    athlete_name: str,
) -> dict[str, Any]:
    if raw.get("schema") != "IRONMAN_TP_RADAR_INPUT_V1":
        raise ValueError("RADAR_INPUT_SCHEMA_MISMATCH")
    if int(raw.get("athlete_id") or 0) != expected_athlete_id:
        raise ValueError("RADAR_ATHLETE_ID_MISMATCH")
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
        "athlete_id": expected_athlete_id,
        "athlete_name": athlete_name,
        "as_of": as_of,
        "status": "YELLOW" if alerts else "GREEN",
        "review_required": bool(alerts),
        "alerts": sorted(alerts, key=lambda x: (x["date"], x["workout_id"], x["category"])),
        "upcoming": sorted(upcoming, key=lambda x: (x["date"], x["workout_id"])),
        "data_quality": {
            "wellness_metrics_count": metrics_count,
            "missing_rpe_workout_ids": sorted(missing_feedback),
            "note": "Assenza di wellness/feedback non equivale a benessere o disponibilita' confermati.",
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


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        json.dump(payload, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        temp_path = Path(tmp.name)
    os.chmod(temp_path, 0o600)
    temp_path.replace(path)
    os.chmod(path, 0o600)


def persist_bundle(raw: dict[str, Any], report: dict[str, Any], output_dir: Path) -> dict[str, str]:
    athlete_id = str(report["athlete_id"])
    as_of = str(report["as_of"])
    target = output_dir / athlete_id
    paths = {
        "input": target / f"input_{as_of}.json",
        "report": target / f"report_{as_of}.json",
        "latest": target / "latest.json",
    }
    _atomic_json(paths["input"], raw)
    _atomic_json(paths["report"], report)
    _atomic_json(paths["latest"], report)
    return {key: str(path) for key, path in paths.items()}


@task(name="fetch-trainingpeaks-radar-input-v2", retries=2, retry_delay_seconds=10)
def fetch_radar_input(
    bridge_base: str,
    athlete_id: int,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    roster = _load_roster()
    if athlete_id not in roster:
        raise ValueError("ATHLETE_NOT_IN_ACTIVE_RADAR_ROSTER")
    return _post_json(
        bridge_base.rstrip("/") + "/v1/radar-input",
        {"athlete_id": str(athlete_id), "start_date": start_date, "end_date": end_date},
    )


@task(name="publish-radar-to-mcp-readback-v2", retries=2, retry_delay_seconds=5)
def publish_radar_task(bridge_base: str, report: dict[str, Any]) -> dict[str, Any]:
    result = _post_json(bridge_base.rstrip("/") + "/v1/radar-result", report)
    if not result.get("stored") or result.get("trainingpeaks_writes") != 0:
        raise RuntimeError("RADAR_RESULT_SINK_READBACK_FAILED")
    return result


@flow(name="ironman-coaching-radar-athlete-v2", retries=0, log_prints=False)
def coaching_radar_athlete_flow(
    athlete_id: int,
    as_of: str | None = None,
    lookback_days: int = 3,
    lookahead_days: int = 3,
    bridge_base: str = DEFAULT_BRIDGE_BASE,
    output_dir: str = str(DEFAULT_OUTPUT_DIR),
) -> dict[str, Any]:
    roster = _load_roster()
    if athlete_id not in roster:
        raise ValueError("ATHLETE_NOT_IN_ACTIVE_RADAR_ROSTER")
    resolved_as_of = _resolved_as_of(as_of)
    start_date, end_date = _window(resolved_as_of, lookback_days, lookahead_days)
    raw = fetch_radar_input(bridge_base, athlete_id, start_date, end_date)
    report = build_report(raw, resolved_as_of, athlete_id, roster[athlete_id])
    files = persist_bundle(raw, report, Path(output_dir))
    sink = publish_radar_task(bridge_base, report)
    return {
        "stage": "IRONMAN_COACHING_RADAR_ATHLETE_V2_DONE",
        "athlete_id": athlete_id,
        "athlete_name": roster[athlete_id],
        "as_of": resolved_as_of,
        "status": report["status"],
        "alert_count": len(report["alerts"]),
        "evidence_sha256": report["evidence_sha256"],
        "files": files,
        "sink": sink,
        "trainingpeaks_writes": 0,
    }


@flow(name="ironman-coaching-radar-group-v2", retries=0, log_prints=False)
def coaching_radar_group_flow(
    as_of: str | None = None,
    athlete_ids: list[int] | None = None,
    lookback_days: int = 3,
    lookahead_days: int = 3,
    bridge_base: str = DEFAULT_BRIDGE_BASE,
    output_dir: str = str(DEFAULT_OUTPUT_DIR),
) -> dict[str, Any]:
    roster = _load_roster()
    selected = list(roster) if athlete_ids is None else [int(x) for x in athlete_ids]
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("INVALID_GROUP_SELECTION")
    unknown = [x for x in selected if x not in roster]
    if unknown:
        raise ValueError(f"ATHLETE_NOT_IN_ACTIVE_RADAR_ROSTER:{unknown}")

    resolved_as_of = _resolved_as_of(as_of)
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for athlete_id in selected:
        try:
            item = coaching_radar_athlete_flow(
                athlete_id=athlete_id,
                as_of=resolved_as_of,
                lookback_days=lookback_days,
                lookahead_days=lookahead_days,
                bridge_base=bridge_base,
                output_dir=output_dir,
            )
            results.append(item)
        except Exception as exc:
            failures.append({
                "athlete_id": athlete_id,
                "athlete_name": roster[athlete_id],
                "error": f"{type(exc).__name__}:{exc}",
            })

    status_counts: dict[str, int] = {}
    for item in results:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1

    summary = {
        "schema": "IRONMAN_COACHING_RADAR_GROUP_V1",
        "mode": "READ_ONLY",
        "group_id": 74397,
        "group_name": "Alberto",
        "as_of": resolved_as_of,
        "athlete_count_requested": len(selected),
        "athlete_count_completed": len(results),
        "failure_count": len(failures),
        "status_counts": status_counts,
        "athletes": [
            {
                "athlete_id": x["athlete_id"],
                "athlete_name": x["athlete_name"],
                "status": x["status"],
                "alert_count": x["alert_count"],
                "evidence_sha256": x["evidence_sha256"],
            }
            for x in results
        ],
        "failures": failures,
        "trainingpeaks_writes": 0,
    }
    group_dir = Path(output_dir) / "group_74397"
    _atomic_json(group_dir / f"summary_{resolved_as_of}.json", summary)
    _atomic_json(group_dir / "latest.json", summary)

    if failures:
        raise RuntimeError(f"GROUP_RADAR_PARTIAL_FAILURE:{len(failures)}")
    return {
        "stage": "IRONMAN_COACHING_RADAR_GROUP_V2_DONE",
        **summary,
    }
