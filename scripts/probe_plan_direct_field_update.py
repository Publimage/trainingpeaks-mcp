#!/usr/bin/env python3
"""One disposable TrainingPeaks plan field-UPDATE canary, NOT a bulk writer.

Default read-only. Live PUT and restoration need --execute and exact plan ack.
NEVER use this script on athletes, published plans or Intermediate 684602.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PLAN_ID = 684484
PLAN_TITLE = "[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
WORKOUT_ID = 3995256662
ORIGINAL_TITLE = "[MCP TEST] IMINT24W-W01-MON-OTHER-01 | SETTIMANA 1 | Calibrazione e riferimenti"
TEST_TITLE = ORIGINAL_TITLE + " | FIELD PATCH TEST"
START = date(2027, 7, 5)
END = START + timedelta(days=10)
ENDPOINT = f"/plans/v1/plans/{PLAN_ID}/workouts/{WORKOUT_ID}"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def signature(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     default=str, separators=(",", ":")).encode()).hexdigest()


def workout_id(workout: dict) -> int:
    ids = [workout[k] for k in ("workoutId", "planWorkoutId", "id")
           if type(workout.get(k)) is int and workout[k] > 0]
    require(bool(ids) and len(set(ids)) == 1, "Ambiguous provider workout ID")
    return ids[0]


async def snapshot(client: Any) -> tuple[dict, dict, str]:
    p = await client.get(f"/plans/v1/plans/{PLAN_ID}")
    require(not p.is_error and isinstance(p.data, dict), "Plan GET failed")
    plan = p.data
    require(plan.get("planId") == PLAN_ID and plan.get("title") == PLAN_TITLE,
            "Wrong sacrificial plan identity")
    require(plan.get("isPublic") is False and plan.get("price") in (None, 0),
            "Refusing to modify public/priced plan")
    require(plan.get("weekCount") == 1 and plan.get("workoutCount") == 1
            and (plan.get("startDate") or "")[:10] == START.isoformat(),
            "Sacrificial plan baseline no longer matches")
    workouts = await client.get(
        f"/plans/v1/plans/{PLAN_ID}/workouts/{START.isoformat()}/{END.isoformat()}"
    )
    require(not workouts.is_error and isinstance(workouts.data, list)
            and len(workouts.data) == 1, "Expected exactly one native workout")
    workout = workouts.data[0]
    require(workout_id(workout) == WORKOUT_ID
            and (workout.get("workoutDay") or "")[:10] == "2027-07-06",
            "Native workout ID/date drift")
    notes = await client.get(
        f"/plans/v1/plans/{PLAN_ID}/calendarNote/{START.isoformat()}/{END.isoformat()}"
    )
    require(not notes.is_error and isinstance(notes.data, list) and len(notes.data) == 1,
            "Expected one preserved native note")
    return plan, workout, signature(notes.data)


async def run(execute: bool, ack: int | None, backup: Path) -> None:
    from tp_mcp.client import TPClient
    async with TPClient() as client:
        plan, original, note_hash = await snapshot(client)
        require(original.get("title") == ORIGINAL_TITLE, "Original title has drifted")
        print(json.dumps({"stage": "PREFLIGHT", "plan_id": PLAN_ID,
                          "workout_id": WORKOUT_ID, "old_title": original["title"],
                          "will_write": execute}, ensure_ascii=False), flush=True)
        if not execute:
            return
        require(ack == PLAN_ID, "Exact disposable plan acknowledgement required")
        require(not backup.exists(), "Backup exists; refusing repeated PUT until reviewed")
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(json.dumps(
            {"plan_id": PLAN_ID, "workout_id": WORKOUT_ID,
             "workout": original, "notes_sha256": note_hash},
            indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        payload = dict(original)
        payload["title"] = TEST_TITLE
        put = await client._request("PUT", ENDPOINT, json=payload, _retry_on_401=False)
        require(not put.is_error, "CANDIDATE_PUT_REJECTED: no fallback or blind retry")
        _, changed, notes_after = await snapshot(client)
        require(changed.get("title") == TEST_TITLE
                and {k: v for k, v in changed.items() if k != "title"}
                    == {k: v for k, v in original.items() if k != "title"}
                and notes_after == note_hash,
                "Unexpected change after PUT; STOP with original backup")
        print(json.dumps({"stage": "CANARY_VERIFIED", "id_unchanged": True,
                          "other_fields_unchanged": True, "notes_preserved": True}), flush=True)
        restored = await client._request("PUT", ENDPOINT, json=original, _retry_on_401=False)
        require(not restored.is_error, "RESTORE_PUT_FAILED; manual recovery using backup")
        _, final, notes_final = await snapshot(client)
        require(final == original and notes_final == note_hash,
                "RESTORE_READBACK_MISMATCH; manual recovery using backup")
        print(json.dumps({"stage": "FINAL", "success": True,
                          "native_update_proven_on_disposable": True,
                          "original_restored": True, "no_delete_or_create": True}), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--ack-disposable-plan", type=int)
    parser.add_argument("--backup", type=Path, default=Path.home() /
                        ".trainingpeaks-mcp/field_patch_canary_684484_backup.json")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.execute, args.ack_disposable_plan, args.backup))
        return 0
    except Exception as exc:
        print(json.dumps({"stage": "STOP", "reason": str(exc)[:450],
                          "do_not_retry_blindly": True,
                          "intermediate_plan_touched": False}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
