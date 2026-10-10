"""One-shot native Strength Builder -> disposable Training Plan route test.

Local Mac command:
    python scripts/probe_strength_training_plan.py --execute

This is deliberately NOT a generic Training Plan publisher. It creates exactly
one new private, unpriced plan and tries the candidate Peaksware Strength save
format with calendarId set to that new test plan's ID. A provider 200 on its own
does NOT prove the workout appears in the Training Plan Library UI.

Never rerun blindly after a network error, failure, or ambiguous POST.
Leave the existing Intermediate pilot and Beginner completely untouched.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta

import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools import plans, strength

NAME = "[MCP TEST] TP Native Strength Plan Route 2026-10-09"
START = "2027-08-02"
WORKOUT_DATE = "2027-08-04"
STRENGTH_TITLE = "[MCP TEST] Forza A | Base 35' | Strength Builder Plan Probe"
ANCHOR_LIBRARY = 3890637
ANCHOR_ITEM = 14940092
DO_NOT_TARGET = {679801, 684463, 684484, 684206, 941614, 856352}


def check(ok: bool, msg: str) -> None:
    if not ok:
        raise RuntimeError(msg)


def log(stage: str, **kw: object) -> None:
    print(json.dumps({"stage": stage, **kw}, ensure_ascii=False, default=str), flush=True)


BLOCKS = [
    {
        "type": "SingleExercise",
        "title": "Goblet Squat",
        "notes": "3 x 6; RPE 6-7; recupero 90-120 s.",
        "exercises": [{"id": "144", "sets": [{"Reps": 6}] * 3}],
    },
    {
        "type": "SingleExercise",
        "title": "Romanian Deadlift",
        "notes": "3 x 6; RPE 6-7; recupero 90-120 s.",
        "exercises": [{"id": "154", "sets": [{"Reps": 6}] * 3}],
    },
    {
        "type": "SingleExercise",
        "title": "Split Squat",
        "notes": "2 x 6 per lato; RPE 6-7; recupero 75-90 s.",
        "exercises": [{"id": "158", "sets": [{"RepsPerSide": 6}] * 2}],
    },
    {
        "type": "SingleExercise",
        "title": "Elevated Body Weight Calf Raise",
        "notes": "2 x 10 controllate; recupero 60 s.",
        "exercises": [{"id": "553", "sets": [{"Reps": 10}] * 2}],
    },
    {
        "type": "SingleExercise",
        "title": "DB Row",
        "notes": "2 x 8; RPE 6-7; recupero 60-75 s.",
        "exercises": [{"id": "516", "sets": [{"Reps": 8}] * 2}],
    },
    {
        "type": "SingleExercise",
        "title": "Side Plank",
        "notes": "2 x 30 s per lato; recupero 30 s.",
        "exercises": [{"id": "79", "sets": [{"Duration": 30}] * 2}],
    },
]
INSTRUCTIONS = (
    "SOLO LAB. Forza A Intermediate, 35 min. Warm-up 5 min mobilita dinamica "
    "anche/caviglie/torace e una serie leggera dei primi due esercizi. "
    "RPE e recuperi nelle note dei blocchi. Nessun cedimento; 2-4 ripetizioni "
    "in riserva. FUELING: normale alimentazione, acqua secondo sete, "
    "snack se pasto lontano, recupero con carboidrati e proteine. "
    "Nessun video esterno: usare dimostrazioni native TrainingPeaks. "
    "Non eseguire: allenamento di prova su piano privato."
)


async def strength_list(h: httpx.AsyncClient, token: str, plan_id: int) -> tuple[int, object]:
    url = f"{strength.STRENGTH_API_BASE}/rx/activity/v1/workouts/calendar/{plan_id}/{START}/{(date.fromisoformat(START) + timedelta(days=8)).isoformat()}"
    r = await h.get(url, headers=strength._headers(token))
    body = r.json() if r.status_code == 200 else r.text[:300]
    return r.status_code, body


async def main() -> None:
    check(date.fromisoformat(START).weekday() == 0, "Configured start is not Monday.")
    check(len(INSTRUCTIONS) < 1000, "Strength instructions exceed provider limit.")
    check(strength._validate_blocks(BLOCKS) is None, "Invalid strength blocks.")

    before = await plans.tp_list_training_plans()
    check(not before.get("isError"), "Could not verify existing plan library.")
    check(not any(p["title"] == NAME for p in before.get("plans", [])),
          "This one-shot test plan already exists: STOP. Do not rerun.")

    existing_lib = await plans.tp_get_training_plan_workouts(684463)
    check(not existing_lib.get("isError") and existing_lib.get("count") == 13
          and existing_lib.get("calendar_notes_count") == 8,
          "Intermediate preflight changed: STOP.")
    log("PREFLIGHT", protected_intermediate=13, native_notes=8,
        test_plan_title=NAME, test_start=START)

    # One private disposable Training Plan. If this POST is ambiguous, STOP.
    created = await plans.tp_create_training_plan(
        title=NAME, start_date=START, week_count=1,
        description="[MCP TEST] Sacrificabile. Verifica tecnica Strength Builder nativo."
    )
    check(created.get("success") is True and created.get("verified") is True,
          f"Plan creation unverified: {created}. STOP; never rerun blindly.")
    pid = int(created["plan_id"])
    check(pid > 0 and pid not in DO_NOT_TARGET, "Unsafe/ambiguous new plan ID.")
    log("PLAN_CREATED", plan_id=pid, is_private=not created.get("is_public", False))

    # A normal 1-week plan may not acquire startDate until the first workout.
    # Anchor it using an existing verified [MCP TEST] 1-min Other template.
    # This is technical only; no athlete calendar is touched.
    async with TPClient() as client:
        detail = await client.get(f"/plans/v1/plans/{pid}")
        check(not detail.is_error, "Cannot read new plan: STOP.")
        p = detail.data or {}
        check((p.get("title") or "") == NAME
              and p.get("isPublic") is not True
              and p.get("price") in (None, 0),
              "Private test plan identity/price mismatch.")

        lib = await client.get(f"/exerciselibrary/v2/libraries/{ANCHOR_LIBRARY}/items")
        check(not lib.is_error and isinstance(lib.data, list), "Anchor library unavailable.")
        item = next((x for x in lib.data if x.get("exerciseLibraryItemId") == ANCHOR_ITEM), None)
        check(item is not None
              and (item.get("itemName") or "").startswith("[MCP TEST]")
              and item.get("workoutTypeId") == 100,
              "Missing safe 1-min Other anchor template.")
        anchor = await client._request(
            "POST", f"/plans/v1/plans/{pid}/commands/addworkoutfromlibraryitem",
            json={
                "planId": pid,
                "exerciseLibraryItemId": ANCHOR_ITEM,
                "workoutDateTime": START,
            },
            _retry_on_401=False,
        )
        check(not anchor.is_error, f"Anchor POST failed/ambiguous: {anchor.message}. STOP.")

    p = await plans.tp_get_training_plan(pid)
    w = await plans.tp_get_training_plan_workouts(pid)
    check(not p.get("isError") and not w.get("isError")
          and p.get("title") == NAME and p.get("start_date") == START
          and w.get("count") == 1
          and w["workouts"][0]["sport"] == "Other",
          "Plan anchor readback failed: STOP.")
    log("PLAN_ANCHORED", plan_id=pid, workouts=w.get("count"), date=p.get("start_date"))

    async with TPClient() as client:
        athlete_id, token, error = await strength._access(client)
        check(not error and token and athlete_id, "Peaksware authentication failed.")
        check(pid != athlete_id, "Test plan ID collides with authenticated athlete.")
        async with httpx.AsyncClient(timeout=strength.STRENGTH_TIMEOUT) as h:
            status, lst = await strength_list(h, token, pid)
            check(status == 200 and isinstance(lst, list),
                  f"Candidate Strength plan-calendar GET status {status}; STOP.")
            check(not lst, "Strength plan-calendar is already populated: STOP.")
            log("STRENGTH_PRECHECK", plan_id=pid, provider_status=status, existing=0)

            payload = strength._build_payload(
                pid, WORKOUT_DATE, STRENGTH_TITLE, BLOCKS, INSTRUCTIONS,
            )
            # EXPERIMENTAL: may be rejected by API. Post exactly once. NO
            # automatic retry after 401/network timeout/ambiguous response.
            resp = await h.post(
                f"{strength.STRENGTH_API_BASE}/rx/activity/v1/workouts/save",
                headers=strength._headers(token), json=payload,
            )
            if resp.status_code != 200:
                log("STRENGTH_API_REJECTED", status_code=resp.status_code,
                    response=resp.text[:550], plan_id=pid,
                    note="No second POST. Inspect test plan before further tests.")
                return
            data = resp.json().get("data") or {}
            wid = data.get("id")
            check(bool(wid), "200 without workout id: ambiguous, STOP.")
            log("STRENGTH_API_ACCEPTED", workout_id=wid, plan_id=pid)

            details = await h.get(
                f"{strength.STRENGTH_API_BASE}/rx/activity/v1/workouts/{wid}",
                headers=strength._headers(token),
            )
            check(details.status_code == 200, "Strength detail cannot be read back.")
            actual = details.json().get("data") or {}
            check(actual.get("workoutType") == "StructuredStrength"
                  and str(actual.get("calendarId")) == str(pid)
                  and actual.get("title") == STRENGTH_TITLE
                  and len(actual.get("blocks") or []) == 6,
                  "Returned Strength workout does not match plan/date/blocks.")
            prescriptions = sum(
                len(ex.get("sets") or [])
                for b in (actual.get("blocks") or [])
                for ex in (b.get("prescriptions") or [])
            )
            check(prescriptions == 14, "Fourteen Strength sets did not survive.")
            status, native = await strength_list(h, token, pid)
            check(status == 200 and isinstance(native, list), "Strength plan list failed.")
            linked = [v for v in native if str(v.get("id")) == str(wid)]
            check(len(linked) == 1, "Created Strength absent from plan-calendar API.")
            log("STRENGTH_PROVIDER_READBACK_PASS", plan_id=pid,
                workout_id=wid, workout_type="StructuredStrength",
                blocks=6, sets=14, plan_calendar_api_count=len(native))

    # Separate legacy plan API may exclude StructuredStrength by design.
    plan = await plans.tp_get_training_plan(pid)
    cards = await plans.tp_get_training_plan_workouts(pid)
    check(not plan.get("isError") and not cards.get("isError")
          and plan.get("title") == NAME and plan.get("start_date") == START,
          "Final plan metadata readback failed.")
    classic_matches = [z for z in cards.get("workouts", [])
                       if z.get("title") == STRENGTH_TITLE]
    log("FINAL", plan_id=pid, workout_id=wid, strength_api_pass=True,
        classic_plan_reader_matches=len(classic_matches),
        plan_legacy_cards=cards.get("count"),
        interpretation=(
            "Native Strength listed on plan calendar, also in classic Plan reader."
            if classic_matches else
            "Native Strength listed on plan calendar API; verify TP plan UI visually "
            "before declaring Training Plan Library publishing complete."
        ),
        note="Do not rerun. The disposable plan is intentionally left for manual UI check.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                        help="Create one disposable private plan and test native Strength API exactly once.")
    args = parser.parse_args()
    if not args.execute:
        parser.print_help()
        raise SystemExit(2)
    try:
        asyncio.run(main())
    except Exception as exc:
        log("STOP", reason=str(exc)[:450],
            action="Inspect provider state; never rerun the one-shot command blindly.")
        raise SystemExit(1) from None
