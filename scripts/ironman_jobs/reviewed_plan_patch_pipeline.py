"""Single reusable TrainingPeaks plan-workout publisher, bound to a GitHub-reviewed manifest.

The two fixed operator jobs (read-only review and guarded publish) reuse this
module. New batches change only the reviewed JSON manifest in the trusted
repository; no per-batch script or job registration is necessary.

This is ordinary code for future separately approved work. Never select a
previously denied operation as a workaround for platform security controls.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

try:
    from scripts.ironman_jobs.plan_patch_batch_core import (
        PlanPatchStop, canonical, require, run_batch, selected, sha256,
        validate_manifest,
    )
    from scripts.ironman_jobs.tp_plan_readonly_gateway import TrainingPeaksPlanReadGateway
except ModuleNotFoundError:
    from plan_patch_batch_core import (
        PlanPatchStop, canonical, require, run_batch, selected, sha256,
        validate_manifest,
    )
    from tp_plan_readonly_gateway import TrainingPeaksPlanReadGateway

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_FILE = ROOT / "data/ironman_reviewed_plan_patch.json"
JOURNAL_DIR = Path.home() / ".local/state/ironman-operator/reviewed-plan-patches"
APPROVED_OWNER = 2116886


def load_config(path: Path = MANIFEST_FILE) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), "MANIFEST_FILE_NOT_FOUND")
    raw = path.read_text(encoding="utf-8")
    require(len(raw) <= 2_000_000, "MANIFEST_FILE_TOO_LARGE")
    cfg = json.loads(raw)
    require(isinstance(cfg, dict), "MANIFEST_CONFIGURATION_INVALID")
    require(cfg.get("schema") == "IRONMAN_REVIEWED_PLAN_PATCH_CONFIG_V1", "CONFIG_SCHEMA")
    require(cfg.get("configured") is True, "MANIFEST_NOT_YET_CONFIGURED")
    require(set(cfg) == {"schema", "configured", "manifest", "windows",
                         "expected_classic_count", "expected_note_count"},
            "CONFIG_UNEXPECTED_FIELDS")
    manifest = cfg["manifest"]
    digest = validate_manifest(manifest)
    require(manifest["owner_id"] == APPROVED_OWNER, "OWNER_NOT_ALLOWLISTED")
    require(manifest["scope"].startswith(f"trainingpeaks:plan:{manifest['plan_id']}:"),
            "SCOPE_MUST_BIND_PLAN_ID")
    # Two independently reviewed roots: the manifest and its exact provider scope.
    require(type(cfg["expected_classic_count"]) is int
            and cfg["expected_classic_count"] >= len(manifest["items"]),
            "EXPECTED_CLASSIC_COUNT_INVALID")
    require(type(cfg["expected_note_count"]) is int and cfg["expected_note_count"] >= 0,
            "EXPECTED_NOTES_COUNT_INVALID")
    windows = cfg["windows"]
    require(isinstance(windows, list) and 1 <= len(windows) <= 6,
            "WINDOWS_INVALID")
    prev = None
    for window in windows:
        require(isinstance(window, list) and len(window) == 2
                and all(isinstance(x, str) for x in window), "WINDOW_SHAPE")
        try:
            start, end = (date.fromisoformat(x) for x in window)
        except (ValueError, TypeError) as exc:
            raise PlanPatchStop("WINDOW_DATE_INVALID") from exc
        require(start <= end and (end - start).days <= 89, "WINDOW_TOO_WIDE")
        require(prev is None or start > prev, "WINDOWS_OVERLAP")
        prev = end
    cfg["_manifest_sha256"] = digest
    return cfg


def stable(obj: Any) -> Any:
    # TP can refresh write timestamps without changing the prescription.
    if isinstance(obj, dict):
        return {key: stable(value) for key, value in obj.items()
                if key not in {"lastModifiedDate", "lastModified", "modifiedAt"}}
    if isinstance(obj, list):
        return [stable(x) for x in obj]
    return obj


class ReviewedPlanGateway(TrainingPeaksPlanReadGateway):
    """Only PUT existing plan copies that match the reviewed item's ID & delta."""

    def __init__(self, client: Any, cfg: dict[str, Any]) -> None:
        manifest = cfg["manifest"]
        super().__init__(client, manifest["plan_id"],
                         [tuple(x) for x in cfg["windows"]],
                         expected_owner_id=APPROVED_OWNER)
        self.manifest = manifest
        self.allowed = {x["workout_id"]: x for x in manifest["items"]}

    async def put_workout(self, plan_id: int, workout_id: int,
                          payload: dict[str, Any]) -> bool:
        require(plan_id == self.plan_id and workout_id in self.allowed,
                "UNREVIEWED_PLAN_OR_WORKOUT")
        require(payload.get("workoutId") == workout_id, "PAYLOAD_WORKOUT_ID_CHANGED")
        require(await self.get_owner_id() == APPROVED_OWNER, "OWNER_CHANGED_PREWRITE")
        plan = await self.get_plan(plan_id)
        require(plan.get("title") == self.manifest["expected_title"]
                and plan.get("isPublic") is self.manifest["expected_is_public"]
                and plan.get("workoutCount") == self.manifest["expected_workout_count"],
                "PLAN_SCOPE_CHANGED_PREWRITE")
        row = self.allowed[workout_id]
        current = await self.get_workout(plan_id, workout_id)
        # Exactly reviewed fields may be changed. All other provider data is
        # preserved from the most recent native GET (including structured Builder).
        require(stable({k: v for k, v in payload.items()
                        if k not in row["after"]})
                == stable({k: v for k, v in current.items()
                           if k not in row["after"]}),
                "UNREVIEWED_PAYLOAD_FIELDS")
        require(selected(current, row["after"]) == row["before"],
                "PREWRITE_CONTENT_DRIFT")
        require(selected(payload, row["after"]) == row["after"],
                "PAYLOAD_NOT_REVIEWED_DESIRED")
        # Proven, plan-scoped endpoint; never an athlete-calendar update.
        reply = await self.client._request(
            "PUT", f"/plans/v1/plans/{plan_id}/workouts/{workout_id}",
            json=payload, _retry_on_401=False
        )
        if reply.is_error:
            code = getattr(reply, "error_code", None)
            raise PlanPatchStop("TRAININGPEAKS_WRITE_FAILED_" + str(code))
        return True


async def _read_notes(client: Any, cfg: dict[str, Any]) -> list[Any]:
    plan_id = cfg["manifest"]["plan_id"]
    found = []
    for start, end in cfg["windows"]:
        reply = await client.get(f"/plans/v1/plans/{plan_id}/calendarNote/{start}/{end}")
        require(not reply.is_error and isinstance(reply.data, list),
                "PLAN_NATIVE_NOTES_READ_FAILED")
        found.extend(copy.deepcopy(reply.data))
    require(len(found) == cfg["expected_note_count"], "NOTE_COUNT_DRIFT")
    return stable(found)


async def publish(*, execute: bool, config_path: Path = MANIFEST_FILE,
                  journal_dir: Path = JOURNAL_DIR,
                  client: Any | None = None) -> dict[str, Any]:
    """Read all targets/notes; write only with guard, and independently verify all."""
    cfg = load_config(config_path)
    manifest = cfg["manifest"]
    own_client = client is None
    if own_client:
        from tp_mcp.client import TPClient
        async with TPClient() as runtime:
            return await _run(cfg, runtime, execute=execute, journal_dir=journal_dir)
    return await _run(cfg, client, execute=execute, journal_dir=journal_dir)


async def _run(cfg: dict[str, Any], client: Any, *, execute: bool,
               journal_dir: Path) -> dict[str, Any]:
    manifest = cfg["manifest"]
    gateway = ReviewedPlanGateway(client, cfg)
    require(await gateway.get_owner_id() == APPROVED_OWNER, "WRONG_COACH")
    meta = await gateway.get_plan(manifest["plan_id"])
    require(meta.get("title") == manifest["expected_title"]
            and meta.get("isPublic") is manifest["expected_is_public"]
            and meta.get("workoutCount") == manifest["expected_workout_count"],
            "PLAN_METADATA_CHANGED")
    originals = await gateway.list_workouts()
    require(len(originals) == cfg["expected_classic_count"],
            "CLASSIC_WORKOUT_COUNT_DRIFT")
    before = {x["workoutId"]: stable(x) for x in originals}
    require(len(before) == len(originals), "DUPLICATE_WORKOUT_ID")
    target_ids = set(gateway.allowed)
    require(target_ids.issubset(before), "TARGET_MISSING_IN_PLAN")
    for row in manifest["items"]:
        native = before[row["workout_id"]]
        require(selected(native, row["after"]) in (row["before"], row["after"]),
                "PREVIEW_TARGET_DRIFT")
        if "expected_sport_id" in row:
            require(native.get("workoutTypeValueId") == row["expected_sport_id"],
                    "SPORT_SCOPE_MISMATCH")
        if "expected_workout_day" in row:
            require(str(native.get("workoutDay") or "")[:10]
                    == row["expected_workout_day"], "WORKOUT_DAY_DRIFT")
    notes_before = await _read_notes(client, cfg)
    path = (journal_dir / f"plan-{manifest['plan_id']}-{cfg['_manifest_sha256'][:24]}.json")
    report = await run_batch(
        manifest, gateway, path, execute=execute,
        ack_scope=manifest["scope"] if execute else None,
        reviewed_manifest_sha256=cfg["_manifest_sha256"] if execute else None,
    )
    if execute:
        after_rows = await gateway.list_workouts()
        require(len(after_rows) == len(originals), "FINAL_WORKOUT_COUNT_DRIFT")
        after = {x["workoutId"]: stable(x) for x in after_rows}
        require(set(after) == set(before), "WORKOUT_SET_CHANGED")
        for wid in before:
            if wid not in target_ids:
                require(after[wid] == before[wid], "NON_TARGET_CHANGED")
            else:
                row = gateway.allowed[wid]
                require(selected(after[wid], row["after"]) == row["after"],
                        "TARGET_NOT_UPDATED")
                require({k: v for k, v in after[wid].items()
                         if k not in row["after"]}
                        == {k: v for k, v in before[wid].items()
                            if k not in row["after"]}, "UNREVIEWED_FIELDS_CHANGED")
        require(await _read_notes(client, cfg) == notes_before,
                "PLAN_NATIVE_NOTES_CHANGED")
        end = await gateway.get_plan(manifest["plan_id"])
        require(end.get("title") == manifest["expected_title"]
                and end.get("isPublic") is manifest["expected_is_public"]
                and end.get("workoutCount") == manifest["expected_workout_count"],
                "PLAN_FINAL_METADATA_CHANGED")
    return {
        "stage": "PLAN_PATCH_PUBLISH_VERIFIED" if execute else "PLAN_PATCH_PREVIEW_PASS",
        "plan": manifest["plan_id"], "workouts_total": len(originals),
        "notes_total": len(notes_before), "manifest_sha256": cfg["_manifest_sha256"],
        "targets": len(target_ids), "provider_writes": report["provider_writes"],
        "public_preserved": manifest["expected_is_public"],
        "readback_verified": bool(execute),
        "athlete_calendar_writes": 0, "library_writes": 0,
    }


def require_explicit_target(cfg: dict[str, Any], requested_plan_id: str | None) -> None:
    """Fail closed before any provider read/write when the caller intent is stale."""
    require(isinstance(requested_plan_id, str) and requested_plan_id.isdecimal(),
            "REQUEST_TARGET_PLAN_ID_REQUIRED")
    require(int(requested_plan_id) == cfg["manifest"]["plan_id"],
            "STOP_TARGET_MISMATCH")



def require_explicit_change_request(cfg: dict[str, Any], requested_scope: str | None,
                                    requested_ids_json: str | None) -> None:
    """Protect against a stale manifest for a NEW edit of the SAME plan.

    The independent request scope and exact IDs are supplied by the operator,
    never resolved from the last manifest file.
    """
    manifest = cfg["manifest"]
    require(isinstance(requested_scope, str)
            and requested_scope.startswith("trainingpeaks:plan:"),
            "REQUEST_SCOPE_REQUIRED")
    require(requested_scope == manifest["scope"], "STOP_REQUEST_SCOPE_MISMATCH")
    require(isinstance(requested_ids_json, str)
            and len(requested_ids_json) <= 5000, "REQUEST_WORKOUT_IDS_REQUIRED")
    try:
        ids = json.loads(requested_ids_json)
    except ValueError as exc:
        raise PlanPatchStop("REQUEST_WORKOUT_IDS_INVALID") from exc
    require(type(ids) is list and 1 <= len(ids) <= 150
            and all(type(x) is int and x > 0 for x in ids)
            and len(ids) == len(set(ids)), "REQUEST_WORKOUT_IDS_INVALID")
    expected_ids = [x["workout_id"] for x in manifest["items"]]
    require(sorted(ids) == sorted(expected_ids), "STOP_REQUEST_RESOURCE_MISMATCH")


def run_main(*, execute: bool) -> None:
    try:
        # The permanent read-only job can be health-checked even before a new
        # reviewed work item is activated. It must never fabricate an empty write.
        if not execute:
            current = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
            if (current.get("schema") == "IRONMAN_REVIEWED_PLAN_PATCH_CONFIG_V1"
                    and current.get("configured") is False):
                print(json.dumps({
                    "stage": "PLAN_PATCH_NO_ACTIVE_MANIFEST",
                    "provider_writes": 0,
                    "ready_for_future_reviewed_manifest": True,
                }), flush=True)
                return
        # A leftover reviewed manifest must never select the destination.
        # The operator supplies a separate, explicit live-verified plan ID.
        cfg = load_config()
        require_explicit_target(cfg, os.environ.get("IRONMAN_REQUEST_TARGET_PLAN_ID"))
        require_explicit_change_request(
            cfg, os.environ.get("IRONMAN_REQUEST_TARGET_SCOPE"),
            os.environ.get("IRONMAN_REQUEST_WORKOUT_IDS_JSON"))
        print(json.dumps(asyncio.run(publish(execute=execute)),
                         ensure_ascii=False, sort_keys=True), flush=True)
    except Exception as exc:
        print(json.dumps({"stage": "PLAN_PATCH_SAFE_STOP",
                          "reason": str(exc)[:220] if isinstance(exc, PlanPatchStop)
                          else type(exc).__name__,
                          "provider_outcome": "NOT_VERIFIED_CHECK_JOURNAL_AND_PROVIDER",
                          "no_auto_retry": True}), flush=True)
        raise SystemExit(91) from exc
