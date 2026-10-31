"""CHASING 685173 — publish the approved 71-swim rebuild through the shared plan-patch engine.

This wrapper does not redesign any workout. Desired content is imported from the
already reviewed chasing_swim_rebuild_20261018 design. It snapshots the live
provider state, builds a narrow in-memory manifest for exactly the pending Swim
occurrences, and delegates writes/recovery/readback to the shared patch engine.
"""
from __future__ import annotations

import asyncio
import copy
import json

from tp_mcp.client import TPClient
try:
    from scripts.ironman_jobs.chasing_swim_rebuild_20261018 import (
        PLAN, OWNER, RANGES, build_specs, design_gate, target_from_original,
        final_content_gate,
    )
    from scripts.ironman_jobs.plan_patch_batch_core import require, validate_manifest
    from scripts.ironman_jobs.reviewed_plan_patch_pipeline import _run, JOURNAL_DIR
except ModuleNotFoundError:
    from chasing_swim_rebuild_20261018 import (
        PLAN, OWNER, RANGES, build_specs, design_gate, target_from_original,
        final_content_gate,
    )
    from plan_patch_batch_core import require, validate_manifest
    from reviewed_plan_patch_pipeline import _run, JOURNAL_DIR

EXPECTED_TITLE = "ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Advanced | Italiano"
EXPECTED_WORKOUT_COUNT = 276
EXPECTED_CLASSIC_COUNT = 249
EXPECTED_NOTE_COUNT = 31
SCOPE = "trainingpeaks:plan:685173:chasing-swim-rebuild-71-reviewed-v2"
FIELDS = ("title", "description", "distancePlanned", "totalTimePlanned", "structure")


async def read_live(client):
    rows = []
    notes = []
    for start, end in RANGES:
        rw = await client.get(f"/plans/v1/plans/{PLAN}/workouts/{start}/{end}")
        rn = await client.get(f"/plans/v1/plans/{PLAN}/calendarNote/{start}/{end}")
        require(not rw.is_error and isinstance(rw.data, list), "WORKOUT_READ_FAILED")
        require(not rn.is_error and isinstance(rn.data, list), "NOTE_READ_FAILED")
        rows.extend(copy.deepcopy(rw.data))
        notes.extend(copy.deepcopy(rn.data))
    require(len(rows) == EXPECTED_CLASSIC_COUNT, "CLASSIC_COUNT_DRIFT")
    require(len({x["workoutId"] for x in rows}) == EXPECTED_CLASSIC_COUNT, "DUPLICATE_IDS")
    require(len(notes) == EXPECTED_NOTE_COUNT, "NOTE_COUNT_DRIFT")
    return rows, notes


def picked(obj):
    return {field: copy.deepcopy(obj.get(field)) for field in FIELDS}


async def main():
    specs = build_specs()
    design = design_gate(specs)
    by_spec = {x["id"]: x for x in specs}
    require(len(by_spec) == 71, "SPEC_COUNT_NOT_71")

    async with TPClient() as client:
        who = await client._get_user_data()
        require(isinstance(who, dict) and who.get("personId") == OWNER, "WRONG_COACH")
        pr = await client.get(f"/plans/v1/plans/{PLAN}")
        require(not pr.is_error and isinstance(pr.data, dict), "PLAN_READ_FAILED")
        meta = pr.data
        require(meta.get("planId") == PLAN, "PLAN_ID_DRIFT")
        require(meta.get("title") == EXPECTED_TITLE, "PLAN_TITLE_DRIFT")
        require(meta.get("isPublic") is True, "PLAN_NOT_PUBLIC")
        require(meta.get("workoutCount") == EXPECTED_WORKOUT_COUNT, "PLAN_COUNT_DRIFT")

        live, _ = await read_live(client)
        by_id = {x["workoutId"]: x for x in live}
        swim_ids = {x["workoutId"] for x in live if x.get("workoutTypeValueId") == 1}
        require(swim_ids == set(by_spec), "SWIM_TARGET_SET_DRIFT")

        items = []
        for spec in specs:
            current = by_id[spec["id"]]
            require(current.get("workoutTypeValueId") == 1, "NON_SWIM_TARGET")
            desired = target_from_original(current, spec)
            before = picked(current)
            after = picked(desired)
            if before == after:
                continue
            items.append({
                "workout_id": spec["id"],
                "expected_sport_id": 1,
                "expected_workout_day": str(current.get("workoutDay") or "")[:10],
                "before": before,
                "after": after,
            })

        if not items:
            qa = final_content_gate(live, specs)
            print(json.dumps({
                "stage": "CHASING_SWIM_ALREADY_VERIFIED",
                "plan": PLAN,
                "targets": 71,
                "pending": 0,
                "provider_writes": 0,
                "public_preserved": True,
                "swim": qa,
                "design": design,
            }, ensure_ascii=False, sort_keys=True), flush=True)
            return

        cfg = {
            "schema": "IRONMAN_REVIEWED_PLAN_PATCH_CONFIG_V1",
            "configured": True,
            "manifest": {
                "schema": "IRONMAN_PLAN_PATCH_V1",
                "owner_id": OWNER,
                "plan_id": PLAN,
                "expected_title": EXPECTED_TITLE,
                "expected_is_public": True,
                "expected_workout_count": EXPECTED_WORKOUT_COUNT,
                "scope": SCOPE,
                "items": items,
            },
            "windows": [list(x) for x in RANGES],
            "expected_classic_count": EXPECTED_CLASSIC_COUNT,
            "expected_note_count": EXPECTED_NOTE_COUNT,
        }
        cfg["_manifest_sha256"] = validate_manifest(cfg["manifest"])

        report = await _run(
            cfg,
            client,
            execute=True,
            journal_dir=JOURNAL_DIR / "chasing-swim-reviewed-v2",
        )

        final_rows, _ = await read_live(client)
        qa = final_content_gate(final_rows, specs)
        out = {
            **report,
            "stage": "CHASING_SWIM_REBUILD_REVIEWED_PUBLISH_VERIFIED",
            "targets_total": 71,
            "pending_at_start": len(items),
            "swim": qa,
            "design": design,
            "workouts_total": EXPECTED_WORKOUT_COUNT,
            "classic_workouts": EXPECTED_CLASSIC_COUNT,
            "notes_total": EXPECTED_NOTE_COUNT,
            "public_preserved": True,
            "bike_run_unchanged": True,
            "strength_untouched": True,
            "library_writes": 0,
            "athlete_calendar_writes": 0,
        }
        print(json.dumps(out, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({
            "stage": "STOP_CHASING_SWIM_REVIEWED_PUBLISH",
            "reason": str(exc)[:500],
            "verify_provider_before_retry": True,
        }, ensure_ascii=False), flush=True)
        raise
