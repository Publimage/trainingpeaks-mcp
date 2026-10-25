"""One-shot deletion-route proof on a disposable TrainingPeaks plan ONLY.

Run from the repo's activated virtualenv:
  python scripts/probe_training_plan_delete.py                 # READ-ONLY preflight
  python scripts/probe_training_plan_delete.py --execute       # disposable test plan

This script NEVER sends a request to published Beginner 679801, Intermediate
pilot 684463, or any athlete calendar. It NEVER deletes a real training plan
workout. No authentication tokens, cookies or HAR are printed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from typing import Any

from tp_mcp.client import TPClient

LAB_TITLE = "[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
LAB_START = date(2027, 7, 5)  # Monday; far from the protected pilot
LAB_LIBRARY_ID = 3890637
LAB_TEMPLATE_ID = 14940092
LAB_TEMPLATE_TITLE = (
    "[MCP TEST] IMINT24W-W01-MON-OTHER-01 | "
    "SETTIMANA 1 | Calibrazione e riferimenti"
)
NOTE_TITLE = "[MCP TEST] DELETE PROBE | Monday anchor note"
NOTE_TEXT = "Disposable plan only. Verify Monday date anchor after removing a workout."
PROTECTED_PLAN_IDS = frozenset({679801, 684463, 684206})
DAYS = tuple(LAB_START + timedelta(days=i) for i in range(3))
LAB_END = LAB_START + timedelta(days=8)


class ProbeStopped(Exception):
    """A preflight or post-write safety gate did not pass."""


def _must(value: bool, explanation: str) -> None:
    if not value:
        raise ProbeStopped(explanation)


def _valid_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _workout_id(workout: dict[str, Any]) -> int | None:
    ids = [
        workout[key] for key in ("workoutId", "planWorkoutId", "id")
        if _valid_id(workout.get(key)) is not None
    ]
    return ids[0] if ids and len(set(ids)) == 1 else None


def _error_name(response: Any) -> str:
    code = getattr(response, "error_code", None)
    return str(getattr(code, "value", "API_ERROR")) if code else "API_ERROR"


async def _get(client: TPClient, endpoint: str, label: str) -> Any:
    result = await client.get(endpoint)
    _must(not result.is_error, f"{label}: GET failed ({_error_name(result)}).")
    return result.data


async def _post(client: TPClient, endpoint: str, payload: dict[str, Any], label: str) -> Any:
    result = await client.post(endpoint, json=payload)
    _must(
        not result.is_error,
        f"{label}: POST was not confirmed ({_error_name(result)}). "
        "Inspect the disposable plan; do not repeat automatically.",
    )
    return result.data


async def _list_plans(client: TPClient) -> list[dict[str, Any]]:
    plans = await _get(client, "/plans/v1/plans", "Training Plan listing")
    _must(isinstance(plans, list), "Unexpected Training Plan listing format.")
    _must(all(isinstance(p, dict) for p in plans), "Unexpected Training Plan listing entries.")
    return plans


async def _read_plan(client: TPClient, plan_id: int) -> dict[str, Any]:
    details = await _get(client, f"/plans/v1/plans/{plan_id}", "Disposable plan detail")
    _must(isinstance(details, dict), "Unexpected Training Plan details.")
    _must(details.get("planId") == plan_id, "Training Plan ID mismatch.")
    _must((details.get("title") or "").strip() == LAB_TITLE, "Training Plan title mismatch.")
    _must(details.get("isPublic") is False, "Disposable Training Plan is not private.")
    _must(details.get("price") in (None, 0), "Disposable Training Plan is priced.")
    _must(plan_id not in PROTECTED_PLAN_IDS, "Attempt to touch a protected plan.")
    return details


async def _workouts(client: TPClient, plan_id: int) -> list[dict[str, Any]]:
    payload = await _get(
        client,
        f"/plans/v1/plans/{plan_id}/workouts/{LAB_START.isoformat()}/{LAB_END.isoformat()}",
        "Disposable plan workout readback",
    )
    _must(isinstance(payload, list), "Unexpected workout list: stop.")
    _must(all(isinstance(item, dict) for item in payload), "Unexpected workout item: stop.")
    return payload


async def _notes(client: TPClient, plan_id: int) -> list[dict[str, Any]]:
    payload = await _get(
        client,
        f"/plans/v1/plans/{plan_id}/calendarNote/{LAB_START.isoformat()}/{LAB_END.isoformat()}",
        "Disposable plan note readback",
    )
    _must(isinstance(payload, list), "Unexpected plan note list: stop.")
    _must(all(isinstance(item, dict) for item in payload), "Unexpected plan note item: stop.")
    return payload


def _cards_by_day(workouts: list[dict[str, Any]], expected_days: tuple[date, ...]) -> dict[str, int]:
    _must(len(workouts) == len(expected_days), "Unexpected number of disposable workouts.")
    matched: dict[str, int] = {}
    for item in workouts:
        day = (item.get("workoutDay") or "")[:10]
        _must(day in {d.isoformat() for d in expected_days}, "Unexpected workout date.")
        _must((item.get("title") or "").strip() == LAB_TEMPLATE_TITLE, "Unexpected workout title.")
        _must(item.get("workoutTypeValueId") == 100, "Test item is not an Other workout.")
        _must(item.get("structure") is None, "Test item has workout structure.")
        duration = item.get("totalTimePlanned")
        _must(isinstance(duration, (int, float)), "Missing planned duration.")
        _must(abs(duration - 1 / 60) < 0.0001, "Test item is not one minute long.")
        workout_id = _workout_id(item)
        _must(workout_id is not None, "Cannot identify a disposable workout's provider ID.")
        _must(day not in matched, "Duplicate card on disposable test day.")
        matched[day] = workout_id
    _must(len(set(matched.values())) == len(expected_days), "Ambiguous duplicated workout IDs.")
    return matched


def _assert_monday_note(notes: list[dict[str, Any]]) -> None:
    _must(len(notes) == 1, "Expected exactly one native note in disposable plan.")
    only = notes[0]
    _must((only.get("title") or "").strip() == NOTE_TITLE, "Unexpected native note title.")
    _must(only.get("description") == NOTE_TEXT, "Native note text changed.")
    _must((only.get("noteDate") or only.get("date") or "")[:10] == LAB_START.isoformat(),
          "Native note date changed.")


async def _delete_once(client: TPClient, plan_id: int, workout_id: int, label: str) -> str:
    _must(plan_id not in PROTECTED_PLAN_IDS, "Protected plan DELETE blocked.")
    _must(_valid_id(workout_id) is not None, "No verified workout ID.")
    endpoint = f"/plans/v1/plans/{plan_id}/workouts/{workout_id}"
    # Explicitly DISABLE TPClient's automatic 401 retry for this destructive request.
    result = await client._request("DELETE", endpoint, _retry_on_401=False)
    _must(
        not result.is_error,
        f"{label}: DELETE response {_error_name(result)}. "
        "Do NOT retry: read the disposable plan before any further action.",
    )
    return endpoint


async def run(execute: bool) -> dict[str, Any]:
    async with TPClient() as client:
        # Read-only preflight: both the testing library item and plan namespace.
        items = await _get(
            client, f"/exerciselibrary/v2/libraries/{LAB_LIBRARY_ID}/items",
            "Disposable Other template",
        )
        _must(isinstance(items, list), "Unexpected Workout Library response.")
        templates = [
            item for item in items if isinstance(item, dict)
            and item.get("exerciseLibraryItemId") == LAB_TEMPLATE_ID
            and (item.get("itemName") or "").strip() == LAB_TEMPLATE_TITLE
        ]
        _must(len(templates) == 1, "Expected disposable Other library template not uniquely found.")
        plans = await _list_plans(client)
        _must(
            not any((p.get("title") or "").strip() == LAB_TITLE for p in plans),
            "Disposable plan title already exists; STOP rather than duplicate/retry.",
        )
        if not execute:
            return {
                "status": "READ_ONLY_PREFLIGHT_PASS",
                "live_write": False,
                "disposable_plan_title": LAB_TITLE,
                "template_id": LAB_TEMPLATE_ID,
                "test_days": [d.isoformat() for d in DAYS],
                "protected_plan_ids": sorted(PROTECTED_PLAN_IDS),
            }

        # Only a disposable, private, one-week plan can be created.
        created = await _post(client, "/plans/v1/plans", {
            "title": LAB_TITLE,
            "startDate": f"{LAB_START.isoformat()}T00:00:00",
            "weekCount": 1,
            "dayCount": 7,
            "isPublic": False,
        }, "Create disposable private Training Plan")
        candidate_id = (created or {}).get("planId") or (created or {}).get("id") if isinstance(created, dict) else None
        if _valid_id(candidate_id) is None:
            by_title = [
                p for p in await _list_plans(client)
                if (p.get("title") or "").strip() == LAB_TITLE
            ]
            _must(len(by_title) == 1, "Plan created but identity not unique: STOP, no retry.")
            candidate_id = by_title[0].get("planId")
        plan_id = _valid_id(candidate_id)
        _must(plan_id is not None, "No trustworthy ID for disposable Training Plan.")
        await _read_plan(client, plan_id)

        # Materialize three one-minute Other cards. Wednesday is non-anchor;
        # Monday is the date anchor; Tuesday stays after the anchor test.
        for index, workout_day in enumerate(DAYS):
            await _read_plan(client, plan_id)
            await _post(
                client,
                f"/plans/v1/plans/{plan_id}/commands/addworkoutfromlibraryitem",
                {
                    "planId": plan_id,
                    "exerciseLibraryItemId": LAB_TEMPLATE_ID,
                    "workoutDateTime": workout_day.isoformat(),
                },
                f"Insert disposable Other on day {index + 1}",
            )
            cards = await _workouts(client, plan_id)
            _cards_by_day(cards, DAYS[:index + 1])
            if index == 0:
                state = await _read_plan(client, plan_id)
                _must(
                    (state.get("startDate") or "")[:10] == LAB_START.isoformat(),
                    "Disposable plan did not anchor to Monday; STOP.",
                )

        await _post(
            client, f"/plans/v1/plans/{plan_id}/calendarNote",
            {
                "planId": plan_id,
                "title": NOTE_TITLE,
                "noteDate": LAB_START.isoformat(),
                "description": NOTE_TEXT,
                "attachments": [],
                "standardFormatDate": "Week 1, Monday",
            },
            "Add disposable Monday native note",
        )
        _assert_monday_note(await _notes(client, plan_id))
        before_ids = _cards_by_day(await _workouts(client, plan_id), DAYS)
        _must(
            (await _read_plan(client, plan_id)).get("startDate", "")[:10]
            == LAB_START.isoformat(),
            "Unexpected Monday anchor before DELETE.",
        )

        # PROOF #1: one actual non-anchor DELETE (Wednesday) on sacrificial plan.
        first_route = await _delete_once(
            client, plan_id, before_ids[DAYS[2].isoformat()],
            "Disposable non-anchor deletion",
        )
        after_first = _cards_by_day(await _workouts(client, plan_id), DAYS[:2])
        _must(
            after_first[DAYS[0].isoformat()] == before_ids[DAYS[0].isoformat()]
            and after_first[DAYS[1].isoformat()] == before_ids[DAYS[1].isoformat()],
            "Non-anchor DELETE changed another test workout: STOP.",
        )
        _assert_monday_note(await _notes(client, plan_id))
        _must(
            (await _read_plan(client, plan_id)).get("startDate", "")[:10]
            == LAB_START.isoformat(),
            "Date anchor changed after non-anchor deletion: STOP.",
        )

        # PROOF #2: does removing Monday's seed shift the date despite a
        # remaining Tuesday workout and a NATIVE Monday note?
        second_route = await _delete_once(
            client, plan_id, before_ids[DAYS[0].isoformat()],
            "Disposable Monday anchor deletion",
        )
        after_anchor = _cards_by_day(await _workouts(client, plan_id), (DAYS[1],))
        _must(
            after_anchor[DAYS[1].isoformat()] == before_ids[DAYS[1].isoformat()],
            "Removing Monday altered Tuesday's surviving workout: STOP.",
        )
        _assert_monday_note(await _notes(client, plan_id))
        detail = await _read_plan(client, plan_id)
        anchor_after = (detail.get("startDate") or "")[:10] or None

        return {
            "status": "DISPOSABLE_PLAN_ROUTE_PROBE_PASS",
            "real_delete_tested": True,
            "target_intermediate_touched": False,
            "beginner_touched": False,
            "disposable_plan_id": plan_id,
            "route": "/plans/v1/plans/{plan_id}/workouts/{workout_id}",
            "non_anchor_route": first_route,
            "monday_anchor_route": second_route,
            "workout_survivor_id": after_anchor[DAYS[1].isoformat()],
            "native_monday_note_preserved": True,
            "start_date_before": LAB_START.isoformat(),
            "start_date_after_anchor_removal": anchor_after,
            "monday_anchor_preserved": anchor_after == LAB_START.isoformat(),
            "safe_to_remove_real_pilot_monday_anchor":
                anchor_after == LAB_START.isoformat(),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true",
        help="CREATE a disposable [MCP TEST] plan and issue two DELETEs THERE only.",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.execute))
    except ProbeStopped as exc:
        print(json.dumps({"status": "STOP", "reason": str(exc), "do_not_retry": True},
                         ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:
        # Never echo exception details that might contain request headers.
        print(json.dumps({
            "status": "STOP",
            "reason": f"Unexpected {type(exc).__name__}; inspect the disposable plan.",
            "do_not_retry": True,
        }, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
