"""Guarded Intermediate TEST native-plan workout title replacement.

The provider has a proven PLAN-scoped DELETE and add-from-library command, but
the connected MCP currently has no plan-scoped title UPDATE. This script replaces
each old copy in plan 684602 with its deduplicated Master copy, one at a time.

Default dry-run only. --execute performs writes in the coach's existing local
authenticated TPClient environment. It never touches athletes or another plan.
It is resumable after readback and never blindly retries ambiguous writes.

Usage:
  python scripts/replace_intermediate_endurance_titles.py
  python scripts/replace_intermediate_endurance_titles.py --execute

After the 229 pass, run the already prepared separate guarded note-title
cleanup script, then verify notes and strength without changing athlete data.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tp_mcp.client import TPClient

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/intermediate_plan_title_release_manifest.json"
PLAN_ID = 684602
PLAN_TITLE = "[MCP TEST] IRONMAN Intermediate Assembly 24W"
FIRST_MONDAY = date(2026, 10, 5)
FINAL_READ_END = date(2027, 3, 30)
ENDURANCE = 229
ALL_WORKOUTS = 259
NOTES = 35
SAFE_LIBRARIES = {3891872, 3892601, 3892602}
SPORT_IDS = {"Swim": 1, "Bike": 2, "Run": 3}


class Stop(Exception):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise Stop(reason)


def emit(**values: Any) -> None:
    print(json.dumps(values, ensure_ascii=False), flush=True)


def load_manifest() -> list[dict[str, Any]]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    require(data.get("plan_id") == PLAN_ID and
            data.get("plan_title") == PLAN_TITLE, "Unexpected plan manifest")
    rows = data.get("workouts", [])
    require(len(rows) == ENDURANCE, "Manifest must have exactly 229 rows")
    seen_ids: set[int] = set()
    seen_slots: set[tuple[Any, ...]] = set()
    for r in rows:
        wid = r.get("workout_id")
        slot = (r.get("week"), r.get("day"), r.get("sport"),
                r.get("description_length"))
        require(type(wid) is int and wid > 0 and wid not in seen_ids,
                "Invalid/duplicate workout ID in manifest")
        require(slot not in seen_slots, "Ambiguous canonical slot in manifest")
        require(r.get("master_library_id") in SAFE_LIBRARIES and
                type(r.get("master_item_id")) is int and
                r["master_item_id"] > 0, "Unsupported Workout Library template")
        require(r.get("title_before", "").startswith("IRONMAN | ") and
                r.get("title_after") and
                r["title_before"] != r["title_after"] and
                "W" + str(r.get("week")).zfill(2) not in r["title_after"],
                "Invalid title update")
        require(type(r.get("description_length")) is int and
                r["description_length"] > 100, "Unverified description")
        require(1 <= r["week"] <= 24 and 1 <= r["day"] <= 168,
                "Date beyond the authorized 24 weeks")
        seen_ids.add(wid)
        seen_slots.add(slot)
    return rows


def workout_id(w: dict[str, Any]) -> int:
    val = w.get("workoutId") or w.get("planWorkoutId") or w.get("id")
    require(type(val) is int and val > 0, "Workout without native ID")
    return val


def day_of(w: dict[str, Any]) -> str:
    return (w.get("workoutDay") or w.get("date") or "")[:10]


def core_structure(value: Any) -> Any:
    """Compare meaningful native TP blocks, not regenerated visualization IDs."""
    if not isinstance(value, dict):
        return None
    return {
        "length_metric": value.get("primaryLengthMetric"),
        "intensity_metric": value.get("primaryIntensityMetric"),
        "groups": [
            (group.get("type"), (group.get("length") or {}).get("value"),
             [(step.get("name"), (step.get("length") or {}).get("value"),
               (step.get("length") or {}).get("unit"),
               step.get("intensityClass"),
               [(target.get("minValue"), target.get("maxValue"))
                for target in (step.get("targets") or [])])
              for step in (group.get("steps") or [])])
            for group in (value.get("structure") or [])
        ],
    }


def protected_workout(w: dict[str, Any]) -> tuple[Any, ...]:
    """Preserve native prescription; ignore only identity/title metadata."""
    duration = float(w.get("totalTimePlanned") or 0)
    distance = float(w.get("distancePlanned") or 0)
    return (day_of(w), w.get("workoutTypeValueId"),
            w.get("description"), round(duration, 6),
            round(distance, 6), w.get("tssPlanned"),
            json.dumps(core_structure(w.get("structure")),
                       sort_keys=True, default=str))


def notes_signature(notes: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return sorted((int(n.get("id") or n.get("calendarNoteId") or n.get("noteId")),
                   n.get("title"), n.get("description"),
                   (n.get("noteDate") or n.get("date") or "")[:10],
                   json.dumps(n.get("attachments") or [],
                              sort_keys=True, default=str)) for n in notes)


async def read(client: TPClient) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    p = await client.get(f"/plans/v1/plans/{PLAN_ID}")
    require(not p.is_error and isinstance(p.data, dict), "Cannot read protected Training Plan")
    details = p.data
    require(details.get("planId") == PLAN_ID and
            details.get("title") == PLAN_TITLE and
            details.get("isPublic") is False and
            details.get("price") in (None, 0) and
            details.get("weekCount") == 24, "Training Plan identity or privacy changed")
    a = await client.get(
        f"/plans/v1/plans/{PLAN_ID}/workouts/"
        f"{FIRST_MONDAY.isoformat()}/{FINAL_READ_END.isoformat()}")
    require(not a.is_error and isinstance(a.data, list),
            "Native Training Plan workout GET unavailable")
    require(all(isinstance(w, dict) for w in a.data),
            "Unexpected workout reader shape")
    n = await client.get(
        f"/plans/v1/plans/{PLAN_ID}/calendarNote/"
        f"{FIRST_MONDAY.isoformat()}/{FINAL_READ_END.isoformat()}")
    require(not n.is_error and isinstance(n.data, list),
            "Training Plan native notes GET unavailable")
    require(len(n.data) == NOTES, "Native notes count drift")
    require(len({workout_id(w) for w in a.data}) == len(a.data),
            "Duplicate native workout IDs")
    return details, a.data, n.data


def candidate(row: dict[str, Any], workouts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target_date = (FIRST_MONDAY + timedelta(days=row["day"] - 1)).isoformat()
    family = SPORT_IDS[row["sport"]]
    scoped = [w for w in workouts if day_of(w) == target_date
              and w.get("workoutTypeValueId") == family
              and len(w.get("description") or "") == row["description_length"]]
    before = [w for w in scoped
              if workout_id(w) == row["workout_id"]
              and w.get("title") == row["title_before"]]
    after = [w for w in scoped if w.get("title") == row["title_after"]]
    return before, after


def audit_manifest(rows: list[dict[str, Any]], workouts: list[dict[str, Any]],
                   count_allowed: tuple[int, ...]) -> tuple[int, int]:
    require(len(workouts) in count_allowed,
            f"Endurance count unexpected: {len(workouts)}")
    old_count = new_count = 0
    for row in rows:
        before, after = candidate(row, workouts)
        require(len(before) <= 1 and len(after) <= 1,
                f"Ambiguous copies: {row['canonical_uid']}")
        require(bool(before or after), f"Missing workout: {row['canonical_uid']}")
        if before and after:
            require(protected_workout(before[0]) == protected_workout(after[0]),
                    f"Two different prescriptions: {row['canonical_uid']}")
        old_count += bool(before)
        new_count += bool(after)
    return old_count, new_count


async def run(execute: bool, max_updates: int) -> int:
    rows = load_manifest()
    # Keep the original UI-seeded W1 swim test for the last guarded operation.
    rows.sort(key=lambda row: row["workout_id"] == 3996039593)
    async with TPClient() as client:
        plan, original, notes = await read(client)
        # A previously interrupted copy may have created ONE extra workout.
        require(plan.get("workoutCount") in (ALL_WORKOUTS, ALL_WORKOUTS + 1),
                "Unexpected total workout count; inspect before any write")
        initial_notes = notes_signature(notes)
        old_count, new_count = audit_manifest(rows, original,
                                              (ENDURANCE, ENDURANCE + 1))
        require(len(original) == ENDURANCE or
                sum(bool(candidate(x, original)[0] and candidate(x, original)[1])
                    for x in rows) == 1,
                "More than one pending replacement; refuse bulk repair")
        emit(stage="preflight", plan_id=PLAN_ID, dry_run=not execute,
             total=len(rows), old_titles=old_count, new_titles=new_count,
             native_notes=len(notes), provider_total=plan["workoutCount"])
        if not execute:
            return 0

        updates = 0
        for row in rows:
            if updates >= max_updates:
                break
            plan, live, note_list = await read(client)
            require(notes_signature(note_list) == initial_notes,
                    "Native notes changed; stop")
            before, after = candidate(row, live)
            require(len(before) <= 1 and len(after) <= 1,
                    "Unexpected source/target number")
            if after and not before:
                require(len(live) == ENDURANCE and
                        plan.get("workoutCount") == ALL_WORKOUTS,
                        "Already corrected workout but total count differs")
                continue

            if before and not after:
                require(len(live) == ENDURANCE and
                        plan.get("workoutCount") == ALL_WORKOUTS,
                        "Extra workout before creation; stop")
                # POST to the native plan, NOT to an athlete calendar.
                day = (FIRST_MONDAY +
                       timedelta(days=row["day"] - 1)).isoformat()
                payload = {"planId": PLAN_ID,
                           "exerciseLibraryItemId": row["master_item_id"],
                           "workoutDateTime": day}
                created = await client.post(
                    f"/plans/v1/plans/{PLAN_ID}/commands/addworkoutfromlibraryitem",
                    json=payload)
                if created.is_error:
                    raise Stop("Plan template copy not verified for " +
                               row["canonical_uid"] + "; DO NOT retry blindly")
                # Read back to identify the exact new copy, before any delete.
                plan, live, note_list = await read(client)
                require(notes_signature(note_list) == initial_notes,
                        "Notes changed after copying; stop")
                before, after = candidate(row, live)
                require(len(before) == 1 and len(after) == 1 and
                        len(live) == ENDURANCE + 1 and
                        plan.get("workoutCount") == ALL_WORKOUTS + 1,
                        "New plan workout identity unverified: STOP")
            require(len(before) == 1 and len(after) == 1,
                    "Old and new copies not both present")
            require(protected_workout(before[0]) ==
                    protected_workout(after[0]),
                    "Copy differs from original in prescription/structure; "
                    "old workout preserved: STOP")
            old_id = workout_id(before[0])
            require(old_id == row["workout_id"],
                    "Unexpected old workout ID: STOP")
            endpoint = f"/plans/v1/plans/{PLAN_ID}/workouts/{old_id}"
            deleted = await client._request(
                "DELETE", endpoint, _retry_on_401=False)
            if deleted.is_error:
                raise Stop("Native-plan DELETE uncertain for " +
                           row["canonical_uid"] +
                           "; DO NOT retry without readback")
            plan, live, note_list = await read(client)
            before, after = candidate(row, live)
            require(len(before) == 0 and len(after) == 1 and
                    len(live) == ENDURANCE and
                    plan.get("workoutCount") == ALL_WORKOUTS and
                    notes_signature(note_list) == initial_notes,
                    "Post-replace provider audit FAILED; stop")
            updates += 1
            emit(stage="verified", changed=updates, uid=row["canonical_uid"],
                 workout_id=workout_id(after[0]), title=row["title_after"])

        plan, live, notes_final = await read(client)
        old_count, new_count = audit_manifest(rows, live, (ENDURANCE,))
        require(plan.get("workoutCount") == ALL_WORKOUTS and
                notes_signature(notes_final) == initial_notes,
                "Final total/notes drift")
        emit(stage="final", success=True, updated_this_run=updates,
             old_titles_remaining=old_count, correct_titles=new_count,
             native_notes_preserved=len(notes_final),
             strength_and_all_workouts_total=plan["workoutCount"])
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-updates", type=int, default=229)
    args = parser.parse_args()
    if not 1 <= args.max_updates <= ENDURANCE:
        parser.error("--max-updates must be between 1 and 229")
    try:
        return asyncio.run(run(args.execute, args.max_updates))
    except Exception as exc:
        emit(stage="STOP", success=False, reason=str(exc)[:350],
             do_not_retry_blindly=True, target_plan=PLAN_ID)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
