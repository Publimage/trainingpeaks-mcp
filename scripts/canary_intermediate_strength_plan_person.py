"""One-shot guarded native Strength Builder W1 canary for private Intermediate.

IMPORTANT: Training Plans use relative week/weekday slots. Provider dates below
are storage coordinates only, never athlete execution dates.
Reads LAB and target planPersonId, proves known LAB calendarId mapping,
then runs *at most one* POST using the TARGET planPersonId as calendarId.
No delete, no moving prior LAB workout 33969338, no athlete calendar writes.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, timedelta

import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools.strength import (
    STRENGTH_API_BASE, STRENGTH_TIMEOUT, _access, _build_payload, _headers
)

LAB_ID = 684543
TARGET_ID = 684602
LAB_TITLE = "[MCP TEST] TP Native Strength Plan Route 2026-10-09"
TARGET_TITLE = "[MCP TEST] IRONMAN Intermediate Assembly 24W"
SOURCE_ID = "33969338"
W1_TITLE = "IRONMAN | STRENGTH | W01 WED | Forza A | Base 35'"
LAB_IDS = {"33903234", "33966177", "33969338", "33971120"}
STRUCTURE = (
    ("144", "Goblet Squat", 3, {"Reps": 6}, "RPE 6-7; recupero 90-120 s"),
    ("154", "Romanian Deadlift", 3, {"Reps": 6}, "RPE 6-7; recupero 90-120 s"),
    ("158", "Split Squat", 2, {"RepsPerSide": 6}, "RPE 6-7; recupero 75-90 s"),
    ("553", "Elevated Body Weight Calf Raise", 2, {"Reps": 10}, "Recupero 60 s"),
    ("151", "Single Arm DB Row", 2, {"RepsPerSide": 8}, "RPE 6-7; recupero 60-75 s"),
    ("79", "Side Plank", 2, {"RepsPerSide": 1, "Duration": 30}, "30 s per lato; recupero 30 s"),
)


def output(**fields: object) -> None:
    print(json.dumps(fields, ensure_ascii=False, indent=2))


def valid_plan(p: object, pid: int, title: str, weeks: int, count: int) -> bool:
    return bool(
        isinstance(p, dict)
        and p.get("planId") == pid
        and (p.get("title") or "").strip() == title
        and p.get("weekCount") == weeks
        and p.get("workoutCount") == count
        and p.get("price") in (None, 0)
        and p.get("isPublic") is False
        and p.get("eventPlan") is False
        and p.get("planCategory") == 0
    )


def positive_id(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


async def plan_strength(h: httpx.AsyncClient, access: str, pid: int,
                        start: date, span: int) -> list[dict] | None:
    end = start + timedelta(days=span)
    url = (
        f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{pid}/workouts/"
        f"{start.isoformat()}/{end.isoformat()}"
    )
    r = await h.get(url, headers=_headers(access))
    if r.status_code != 200:
        return None
    try:
        d = r.json()
        if isinstance(d, dict):
            d = d.get("data")
        if not isinstance(d, list) or not all(isinstance(v, dict) for v in d):
            return None
        return d
    except (ValueError, TypeError):
        return None


def ids(items: list[dict]) -> set[str]:
    return {str(w.get("id") or w.get("workoutId")) for w in items}


async def main() -> int:
    if sys.argv[1:] != ["--execute"]:
        output(success=False, read_only=True, error="Use --execute for one permitted private TEST plan canary.")
        return 0

    async with TPClient() as client:
        lab_r = await client.get(f"/plans/v1/plans/{LAB_ID}")
        target_r = await client.get(f"/plans/v1/plans/{TARGET_ID}")
        lab = lab_r.data if not lab_r.is_error else None
        target = target_r.data if not target_r.is_error else None
        if not valid_plan(lab, LAB_ID, LAB_TITLE, 44, 5) or not valid_plan(
            target, TARGET_ID, TARGET_TITLE, 24, 229
        ):
            output(success=False, stage="preflight", wrote=False,
                   reason="Protected plan metadata mismatch",
                   lab_observed={"weeks": lab.get("weekCount"), "count": lab.get("workoutCount"),
                                 "day_count": lab.get("dayCount"),
                                 "privacy_false": lab.get("isPublic") is False}
                                if isinstance(lab, dict) else None,
                   target_observed={"weeks": target.get("weekCount"), "count": target.get("workoutCount"),
                                    "privacy_false": target.get("isPublic") is False}
                                   if isinstance(target, dict) else None)
            return 1

        lab_person = positive_id(lab.get("planPersonId"))
        target_person = positive_id(target.get("planPersonId"))
        lab_owner = positive_id(lab.get("ownerPersonId"))
        target_owner = positive_id(target.get("ownerPersonId"))
        correct_mapping = (
            lab_person is not None and target_person is not None
            and lab_person != target_person
            and lab_owner is not None and lab_owner == target_owner
        )
        if not correct_mapping:
            output(success=False, stage="plan_person_mapping", wrote=False,
                   lab_planPersonId_positive=lab_person is not None,
                   target_planPersonId_positive=target_person is not None,
                   same_planPersonId=lab_person == target_person,
                   same_ownerPersonId=lab_owner is not None and lab_owner == target_owner,
                   reason="Cannot establish isolated planPersonId mapping")
            return 1

        _, access, error = await _access(client)
        if error or not access:
            output(success=False, stage="auth", wrote=False, reason="No authenticated session")
            return 1

        lab_technical_anchor = date.fromisoformat(lab["startDate"][:10])
        lab_original_window = date(2027, 8, 2)
        target_start = date.fromisoformat(target["startDate"][:10])
        if (lab_technical_anchor != date(2026, 10, 7)
            or (lab.get("dayCount") or 0) != 304
            or target_start != date(2026, 10, 5)):
            output(success=False, stage="technical_mapping_guard", wrote=False,
                   reason="Plan coordinates/extent changed; no POST")
            return 1
        w1_wed = target_start + timedelta(days=(2 - target_start.weekday()) % 7)

        async with httpx.AsyncClient(timeout=STRENGTH_TIMEOUT) as h:
            lab_known = await plan_strength(h, access, LAB_ID, lab_original_window, 9)
            lab_orphan = await plan_strength(h, access, LAB_ID, target_start, 9)
            target_w1 = await plan_strength(h, access, TARGET_ID, target_start, 9)
            if (
                lab_known is None or lab_orphan is None or target_w1 is None
                or ids(lab_known) != LAB_IDS - {SOURCE_ID}
                or ids(lab_orphan) != {SOURCE_ID}
                or len(target_w1) != 0
            ):
                output(success=False, stage="membership_guard", wrote=False,
                       lab_known_count=len(lab_known) if lab_known is not None else None,
                       lab_other_count=len(lab_orphan) if lab_orphan is not None else None,
                       intermediate_w1_strength_count=len(target_w1) if target_w1 is not None else None,
                       reason="Native membership changed; no POST")
                return 1

            source_r = await h.get(
                f"{STRENGTH_API_BASE}/rx/activity/v1/workouts/{SOURCE_ID}",
                headers=_headers(access),
            )
            if source_r.status_code != 200:
                output(success=False, stage="source_guard", wrote=False, reason="Source unavailable")
                return 1
            try:
                src = source_r.json().get("data") or {}
            except (ValueError, TypeError):
                src = {}
            instr = src.get("instructions")
            source_calendar = positive_id(src.get("calendarId"))
            # Authoritative causal guard: proven LAB workout was written into
            # plan lab using LAB planPersonId; target has a different one.
            if (
                source_calendar != lab_person
                or str(src.get("id")) != SOURCE_ID
                or src.get("title") != W1_TITLE
                or src.get("workoutType") != "StructuredStrength"
                or len(src.get("blocks") or []) != 6
                or (src.get("snapshot") or {}).get("totalSets") != 14
                or not isinstance(instr, str)
                or not (180 <= len(instr) <= 1000)
            ):
                output(success=False, stage="mapping_guard", wrote=False,
                       source_calendar_matches_lab_planPersonId=source_calendar == lab_person,
                       source_6_blocks=len(src.get("blocks") or []) == 6,
                       source_14_sets=(src.get("snapshot") or {}).get("totalSets") == 14,
                       reason="Cannot verify LAB calendarId mapping to planPersonId; no POST")
                return 1

            blocks = [
                {
                    "type": "SingleExercise", "title": title,
                    "exercises": [{
                        "id": exercise_id, "notes": notes,
                        "sets": [dict(dose) for _ in range(reps)],
                    }],
                }
                for exercise_id, title, reps, dose, notes in STRUCTURE
            ]
            # Crucial fix: calendarId is the destination planPersonId, not
            # source/LAB calendarId. Slot W01 WED is relative.
            payload = _build_payload(
                target_person, w1_wed.isoformat(), W1_TITLE, blocks, instr,
            )

            fresh = await client.get(f"/plans/v1/plans/{TARGET_ID}")
            fresh_lab = await client.get(f"/plans/v1/plans/{LAB_ID}")
            if (
                fresh.is_error or not valid_plan(fresh.data, TARGET_ID, TARGET_TITLE, 24, 229)
                or fresh_lab.is_error or not valid_plan(fresh_lab.data, LAB_ID, LAB_TITLE, 44, 5)
            ):
                output(success=False, stage="last_gate", wrote=False,
                       reason="Training Plan count/identity changed before POST")
                return 1

            output(stage="prepared", relative_slot="W01 WED",
                   target_plan=TARGET_ID, source_id=SOURCE_ID,
                   source_calendar_matches_lab_planPersonId=True,
                   destination_has_distinct_planPersonId=True,
                   blocks=6, sets=14, planned_POSTs=1)
            try:
                resp = await h.post(
                    f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{TARGET_ID}/workouts/save",
                    headers=_headers(access), json=payload
                )
            except httpx.RequestError:
                output(success=False, stage="post", one_post_sent=True,
                       error="AMBIGUOUS_POST", retry=False)
                return 1
            if resp.status_code != 200:
                issues = {}
                try:
                    body = resp.json()
                    if isinstance(body, dict) and isinstance(body.get("errors"), dict):
                        issues = {str(k)[:80]: str(v)[:200]
                                  for k, v in list(body["errors"].items())[:5]}
                except (ValueError, TypeError):
                    pass
                output(success=False, stage="post", one_post_sent=True,
                       http_status=resp.status_code, fields=issues, retry=False)
                return 1
            try:
                p = resp.json().get("data") or {}
                new_id = str(p.get("id") or payload["id"])
            except (ValueError, TypeError, AttributeError):
                output(success=False, stage="post", one_post_sent=True,
                       error="AMBIGUOUS_REPLY", retry=False)
                return 1

            detail_r = await h.get(
                f"{STRENGTH_API_BASE}/rx/activity/v1/workouts/{new_id}",
                headers=_headers(access)
            )
            try:
                detail = detail_r.json().get("data") or {} if detail_r.status_code == 200 else {}
            except (ValueError, TypeError):
                detail = {}
            target_native = await plan_strength(h, access, TARGET_ID, target_start, 9)
            lab_native = await plan_strength(h, access, LAB_ID, target_start, 9)
            result_target = await client.get(f"/plans/v1/plans/{TARGET_ID}")
            result_lab = await client.get(f"/plans/v1/plans/{LAB_ID}")
            final_count = (result_target.data or {}).get("workoutCount") if not result_target.is_error else None
            lab_count = (result_lab.data or {}).get("workoutCount") if not result_lab.is_error else None
            pass_check = (
                detail.get("workoutType") == "StructuredStrength"
                and detail.get("title") == W1_TITLE
                and (detail.get("snapshot") or {}).get("totalSets") == 14
                and len(detail.get("blocks") or []) == 6
                and positive_id(detail.get("calendarId")) == target_person
                and target_native is not None and ids(target_native) == {new_id}
                and lab_native is not None and ids(lab_native) == {SOURCE_ID}
                and final_count == 230 and lab_count == 5
            )
            output(
                success=pass_check, one_post_sent=True,
                plan_id=TARGET_ID, workout_id=new_id,
                target_membership=target_native is not None and new_id in ids(target_native),
                detail_calendar_matches_target_planPersonId=positive_id(detail.get("calendarId")) == target_person,
                blocks=len(detail.get("blocks") or []),
                sets=(detail.get("snapshot") or {}).get("totalSets"),
                target_count_after=final_count, lab_count_after=lab_count,
                original_lab_workout_preserved=lab_native is not None and SOURCE_ID in ids(lab_native),
                retry_allowed=False,
                followup=("Continue remaining 29 only after success" if pass_check else
                          "STOP: inspect provider state before any additional POST")
            )
            return 0 if pass_check else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
