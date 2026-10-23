"""One-shot cleanup of six legacy Other cards in the private Intermediate pilot.

The verified TrainingPeaks plan-scoped DELETE route is installed ONLY for
this local command, not on the always-on MCP server. No athlete calendars or
other Training Plans can be targeted.

Usage: python scripts/cleanup_intermediate_other.py --execute
"""
from __future__ import annotations

import argparse
import asyncio
import json

from tp_mcp.tools import plans

PLAN_ID = 684463
TITLE = "[MCP TEST] IRONMAN Intermediate 24W - Archive Pilot"
START = "2027-01-04"
ROUTE = "/plans/v1/plans/{plan_id}/workouts/{workout_id}"

# Order: non-anchor weekly objectives, editorial cards, W1 Monday anchor last.
# Provider IDs and native note IDs were independently read back from the live
# Training Plan after creation of the replacement notes.
TARGETS = [
    ("[MCP TEST] IMINT24W-W02-MON-OTHER-01 | SETTIMANA 2 | Calibrazione e prima qualità", 3995108366, 2651076),
    ("[MCP TEST] IMINT24W-W03-MON-OTHER-01 | SETTIMANA 3 | Primo blocco pienamente allenante", 3995108703, 2651077),
    ("[MCP TEST] IMINT24W-W04-MON-OTHER-01 | SETTIMANA 4 | Assorbimento attivo", 3995108804, 2651078),
    ("[MCP TEST] IMINT24W-PHASE-W01-W04 | FASE | Calibration / General Development", 3995117977, 2651074),
    ("[MCP TEST] IMINT24W-CONTENT-README-FIRST | README FIRST | INIZIA DA QUI", 3995118305, 2651075),
    ("[MCP TEST] IMINT24W-W01-MON-OTHER-01 | SETTIMANA 1 | Calibrazione e riferimenti", 3995104321, 2651073),
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


async def audit(expected_other: int, expected_total: int) -> None:
    p = await plans.tp_get_training_plan(PLAN_ID)
    r = await plans.tp_get_training_plan_workouts(PLAN_ID)
    require(not p.get("isError") and not r.get("isError"), "Readback unavailable.")
    require(p.get("title") == TITLE, "Pilot Training Plan title drift.")
    require(p.get("start_date") == START, "Monday anchor shifted: STOP.")
    require(p.get("workouts") == expected_total and r.get("count") == expected_total,
            "Plan workout count drift.")
    require(r.get("calendar_notes_status") == "ok", "Native note readback failed.")
    require(r.get("calendar_notes_count") == 8, "Eight native notes must survive.")
    require(sum(w["sport"] == "Other" for w in r["workouts"]) == expected_other,
            "Legacy Other count mismatch.")
    require(sum(w["sport"] != "Other" for w in r["workouts"]) == 13,
            "Thirteen real workouts must survive.")
    # Reject any unexpected native-note loss even if total count coincidentally matches.
    expected_ids = {n for _, _, n in TARGETS}
    native_ids = {n.get("note_id") for n in r.get("calendar_notes", [])}
    require(expected_ids.issubset(native_ids), "Original six native note IDs changed.")


async def main() -> None:
    await audit(expected_other=6, expected_total=19)
    reader = await plans.tp_get_training_plan_workouts(PLAN_ID)
    diag = reader.get("legacy_other_cleanup_readonly") or {}
    require(diag.get("read_only") is True and len(diag.get("items", [])) == 6,
            "No verified six-Other read-only inventory.")
    indexed = {item["title"]: item for item in diag["items"]}
    require(len(indexed) == 6, "Duplicate legacy title detected.")
    for title, wid, nid in TARGETS:
        item = indexed.get(title)
        require(bool(item) and item.get("matching_other_cards") == 1,
                "Old Other missing or duplicated.")
        require(item.get("exact_one_minute_other") is True
                and item.get("matching_native_note") is True,
                "No byte-identical native note replacement.")
        require(item.get("workout_id") == wid and item.get("native_note_id") == nid,
                "Provider workout/note identity drift.")

    # Route confirmed independently on disposable private Training Plan 684484:
    # Wednesday Other removed, Monday anchor Other removed, Tuesday survived,
    # Monday native note survived, and the 2027-07-05 start date did not move.
    # Leave the MCP default disabled; enable the verified route only here.
    plans._VERIFIED_PLAN_WORKOUT_DELETE_TEMPLATE = ROUTE

    for index, (title, wid, _) in enumerate(TARGETS, 1):
        result = await plans.tp_delete_training_plan_other(
            plan_id=PLAN_ID, expected_title=title, dry_run=False,
        )
        require(result.get("success") is True and result.get("deleted") is True,
                f"DELETE #{index} unverified ({result.get('error_code')}). STOP; do not retry.")
        require(result.get("removed_workout_id") == wid,
                f"DELETE #{index} removed unexpected ID. STOP.")
        require(result.get("remaining_other") == 6 - index,
                f"DELETE #{index} has unexpected remaining Other count.")
        require(result.get("real_workouts_preserved") == 13
                and result.get("native_notes_preserved") == 8
                and result.get("start_date_preserved") is True,
                f"DELETE #{index} changed protected content.")
        await audit(expected_other=6 - index, expected_total=19 - index)
        print(f"PASS {index}/6: removed {wid}; 13 workouts and 8 native notes preserved.")

    print(json.dumps({
        "status": "PASS", "plan_id": PLAN_ID,
        "legacy_other_remaining": 0,
        "real_workouts": 13, "native_notes": 8,
        "start_date": START,
    }, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="Delete six exact legacy Other cards from private plan 684463.")
    arguments = parser.parse_args()
    if not arguments.execute:
        parser.print_help()
        raise SystemExit(2)
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({
            "status": "STOP",
            "reason": str(exc)[:200],
            "action": "Inspect live TrainingPeaks plan; do NOT rerun blindly.",
        }, ensure_ascii=False))
        raise SystemExit(1) from None
