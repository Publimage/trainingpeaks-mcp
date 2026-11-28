"""Run the reusable plan-patch engine against ONE private LAB Bike title.

Strict stages: independent baseline -> reviewed single-item patch -> readback ->
reviewed single-item restore -> final full-plan and note readback. NO athlete,
public-plan, Workout Library, native Strength or note writes.

If partial interruption occurs, reread the same LAB and reconcile; a failed
one-shot operator receipt must never be overridden without auditing the LAB.
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

try:
    from scripts.ironman_jobs.plan_patch_batch_core import run_batch, require, sha256, PlanPatchStop
    from scripts.ironman_jobs.tp_private_lab_write_gateway import (
        PrivateLabWriteGateway, LAB_ID, LAB_WORKOUT_ID, LAB_TITLE
    )
except ModuleNotFoundError:
    from plan_patch_batch_core import run_batch, require, sha256, PlanPatchStop
    from tp_private_lab_write_gateway import (
        PrivateLabWriteGateway, LAB_ID, LAB_WORKOUT_ID, LAB_TITLE
    )


OLD = "[MCP TEST] Bike | 3x5' FTP controllato"
CANARY = "[MCP TEST] Bike | 3x5' FTP controllato [LAB writer canary]"
ROOT = Path.home() / ".local/state/ironman-operator"
SCOPE = "trainingpeaks:private-lab:684206:one-bike-title-canary-and-restore"
WINDOW = ("2027-06-18", "2027-07-04")


def manifest(before: str, after: str, phase: str) -> dict:
    return {
        "schema": "IRONMAN_PLAN_PATCH_V1",
        "owner_id": 2116886,
        "plan_id": LAB_ID,
        "expected_title": LAB_TITLE,
        "expected_is_public": False,
        "expected_workout_count": 6,
        "scope": SCOPE + ":" + phase,
        "items": [{
            "workout_id": LAB_WORKOUT_ID,
            "before": {"title": before},
            "after": {"title": after}
        }]
    }


def normalized(value):
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items()
                if k not in {"lastModifiedDate", "lastModified", "modifiedAt"}}
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


async def native_notes(client):
    a, b = WINDOW
    r = await client.get(f"/plans/v1/plans/{LAB_ID}/calendarNote/{a}/{b}")
    require(not r.is_error and isinstance(r.data, list), "LAB_NOTES_READ_FAIL")
    return sha256(normalized(r.data))


async def main():
    from tp_mcp.client import TPClient
    async with TPClient() as client:
        gateway = PrivateLabWriteGateway(client)
        require(await gateway.get_owner_id() == 2116886, "LAB_OWNER_DRIFT")
        plan = await gateway.get_plan(LAB_ID)
        require(plan.get("title") == LAB_TITLE and plan.get("isPublic") is False
                and plan.get("workoutCount") == 6, "LAB_SCOPE_DRIFT")
        items = await gateway.list_workouts()
        require(len(items) == 6, "LAB_ITEMS_NOT_SIX")
        baseline = {x["workoutId"]: normalized(x) for x in items}
        require(LAB_WORKOUT_ID in baseline, "LAB_BIKE_MISSING")
        current_title = baseline[LAB_WORKOUT_ID]["title"]
        require(current_title in {OLD, CANARY}, "LAB_BIKE_TITLE_UNEXPECTED")
        untouched = {k: v for k, v in baseline.items() if k != LAB_WORKOUT_ID}
        target_semantic = {k: v for k, v in baseline[LAB_WORKOUT_ID].items() if k != "title"}
        note_hash = await native_notes(client)
        forward = manifest(OLD, CANARY, "forward")
        reverse = manifest(CANARY, OLD, "restore")
        for phase, spec in (("forward", forward), ("restore", reverse)):
            journal = ROOT / ("plan-patch-private-lab-684206-" + phase + ".json")
            preview = await run_batch(spec, gateway, journal)
            require(preview["provider_writes"] == 0, "LAB_PREVIEW_WRITE_DETECTED")
            result = await run_batch(
                spec, gateway, journal, execute=True,
                ack_scope=spec["scope"],
                reviewed_manifest_sha256=sha256(spec)
            )
            require(result["status"] == "VERIFIED" and result["processed"] == 1,
                    "LAB_PHASE_UNVERIFIED_" + phase)
            require(await native_notes(client) == note_hash,
                    "LAB_NOTES_CHANGED_" + phase)
            print(json.dumps({
                "stage": "LAB_" + phase.upper() + "_VERIFIED",
                "plan": LAB_ID, "item": LAB_WORKOUT_ID,
                "writes": result["provider_writes"],
                "public": False
            }), flush=True)
        end = await gateway.list_workouts()
        require(len(end) == 6, "LAB_COUNT_CHANGED")
        final = {x["workoutId"]: normalized(x) for x in end}
        require({k: v for k, v in final.items() if k != LAB_WORKOUT_ID} == untouched,
                "LAB_OTHER_WORKOUTS_CHANGED")
        require(final[LAB_WORKOUT_ID].get("title") == OLD, "LAB_TITLE_NOT_RESTORED")
        require({k: v for k, v in final[LAB_WORKOUT_ID].items() if k != "title"}
                == target_semantic, "LAB_TARGET_STRUCTURE_CHANGED")
        endplan = await gateway.get_plan(LAB_ID)
        require(endplan.get("isPublic") is False and endplan.get("workoutCount") == 6,
                "LAB_PLAN_STATE_CHANGED")
        require(await native_notes(client) == note_hash, "LAB_NOTES_CHANGED_FINAL")
        print(json.dumps({
            "stage": "REUSABLE_PLAN_WRITER_LAB_FULL_CYCLE_PASS",
            "plan": LAB_ID, "owner": 2116886,
            "forward_put_verified": True, "restore_put_verified": True,
            "all_six_workouts_preserved": True, "notes_preserved": True,
            "public": False, "athlete_writes": 0, "library_writes": 0
        }), flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({
            "stage": "REUSABLE_WRITER_LAB_STOP",
            "type": type(exc).__name__,
            "reason": str(exc)[:240] if isinstance(exc, PlanPatchStop) else "runtime_failure",
            "outcome": "READBACK_REQUIRED_NO_BLIND_RETRY"
        }), flush=True)
        raise SystemExit(97) from exc
