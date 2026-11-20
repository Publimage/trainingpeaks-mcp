"""One guarded native Strength Builder clone into the SACRIFICIAL plan 684543.

Purpose: compare six-block plan attachment against the one-block lab control.
Run ONLY with --execute. Exactly one POST; never auto-retry; independent
readback of plan count, native Strength plan listing, and workout details.
Does not move or delete the original orphan 33969338; no athlete writes.
Training Plan dates are API storage coordinates for W1 Friday, not athlete dates.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, timedelta

import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools.strength import (
    STRENGTH_API_BASE, STRENGTH_TIMEOUT, _access, _build_payload, _headers,
)

LAB_ID = 684543
ASSEMBLY_ID = 684602
SOURCE_ID = "33969338"
LAB_TITLE = "[MCP TEST] TP Native Strength Plan Route 2026-10-09"
ASSEMBLY_TITLE = "[MCP TEST] IRONMAN Intermediate Assembly 24W"
PROBE_TITLE = "[MCP TEST] Six-block Strength association probe W1 FRI"

# Canonical functionally approved native exercise map, matching source 33969338.
EXERCISES = (
    ("144", "Goblet Squat", 3, {"Reps": 6}, "RPE 6-7; recupero 90-120 s"),
    ("154", "Romanian Deadlift", 3, {"Reps": 6}, "RPE 6-7; recupero 90-120 s"),
    ("158", "Split Squat", 2, {"RepsPerSide": 6}, "RPE 6-7; recupero 75-90 s"),
    ("553", "Elevated Body Weight Calf Raise", 2, {"Reps": 10}, "Recupero 60 s"),
    ("151", "Single Arm DB Row", 2, {"RepsPerSide": 8}, "RPE 6-7; recupero 60-75 s"),
    ("79", "Side Plank", 2, {"RepsPerSide": 1, "Duration": 30}, "30 s per lato; recupero 30 s"),
)


def emit(**data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def plan_ok(d: object, identity: int, title: str, weeks: int, count: int) -> bool:
    return (
        isinstance(d, dict) and d.get("planId") == identity
        and (d.get("title") or "").strip() == title
        and d.get("weekCount") == weeks
        and d.get("workoutCount") == count
        and d.get("price") in (None, 0)
        and d.get("isPublic") in (False, None)
    )


def as_items(obj: object) -> list[dict] | None:
    v = obj.get("data") if isinstance(obj, dict) else obj
    if isinstance(v, list) and all(isinstance(it, dict) for it in v):
        return v
    return None


async def get_plan_strength(http: httpx.AsyncClient, access: str, plan_id: int,
                            start: date) -> list[dict] | None:
    end = start + timedelta(days=8)
    url = (
        f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{plan_id}/workouts/"
        f"{start.isoformat()}/{end.isoformat()}"
    )
    r = await http.get(url, headers=_headers(access))
    if r.status_code != 200:
        return None
    try:
        return as_items(r.json())
    except (ValueError, TypeError):
        return None


async def main() -> int:
    if sys.argv[1:] != ["--execute"]:
        emit(success=False, read_only=True, message="No write. Use --execute for one authorised lab POST.")
        return 0

    async with TPClient() as client:
        lab_r = await client.get(f"/plans/v1/plans/{LAB_ID}")
        asm_r = await client.get(f"/plans/v1/plans/{ASSEMBLY_ID}")
        lab = lab_r.data if not lab_r.is_error else None
        assembly = asm_r.data if not asm_r.is_error else None
        if not plan_ok(lab, LAB_ID, LAB_TITLE, 1, 3) or not plan_ok(
            assembly, ASSEMBLY_ID, ASSEMBLY_TITLE, 24, 229
        ):
            emit(success=False, stage="preflight", reason="Protected plan identity/count drift")
            return 1

        start = date.fromisoformat(lab["startDate"][:10])
        # Only API storage coordinate for W1 Friday; athlete start date is not fixed.
        slot = start + timedelta(days=4)
        _, access, auth_error = await _access(client)
        if auth_error or not access:
            emit(success=False, stage="auth", reason="Connection unavailable")
            return 1

        async with httpx.AsyncClient(timeout=STRENGTH_TIMEOUT) as http:
            listed = await get_plan_strength(http, access, LAB_ID, start)
            if listed is None or len(listed) != 2:
                emit(success=False, stage="preflight", reason="Lab native membership count drift")
                return 1
            listed_str = json.dumps(listed, ensure_ascii=False)
            if not all(wid in listed_str for wid in ("33903234", "33966177")):
                emit(success=False, stage="preflight", reason="Lab control identities drift")
                return 1
            if SOURCE_ID in listed_str or PROBE_TITLE in listed_str:
                emit(success=False, stage="preflight", reason="Probe already in lab; refusing duplicate")
                return 1

            source_r = await http.get(
                f"{STRENGTH_API_BASE}/rx/activity/v1/workouts/{SOURCE_ID}",
                headers=_headers(access),
            )
            if source_r.status_code != 200:
                emit(success=False, stage="preflight", reason="Source workout unavailable")
                return 1
            try:
                native = source_r.json().get("data") or {}
            except (ValueError, TypeError):
                native = {}
            snap = native.get("snapshot") or {}
            instructions = native.get("instructions")
            if (
                str(native.get("id")) != SOURCE_ID
                or native.get("workoutType") != "StructuredStrength"
                or not str(native.get("title", "")).startswith(
                    "IRONMAN | STRENGTH | W01 WED | Forza A"
                )
                or snap.get("totalSets") != 14
                or len(native.get("blocks") or []) != 6
                or not isinstance(instructions, str)
                or not 180 <= len(instructions) <= 1000
            ):
                emit(success=False, stage="preflight", reason="Source content or identity drift")
                return 1

            blocks = [
                {
                    "type": "SingleExercise",
                    "title": title,
                    "exercises": [
                        {
                            "id": exid,
                            "notes": notes,
                            "sets": [dict(dose) for _ in range(n)],
                        }
                    ],
                }
                for exid, title, n, dose, notes in EXERCISES
            ]
            payload = _build_payload(
                int(native["calendarId"]),
                slot.isoformat(),
                PROBE_TITLE,
                blocks,
                instructions,
            )
            # Second fresh count gate at moment of POST.
            refreshed = await client.get(f"/plans/v1/plans/{LAB_ID}")
            if refreshed.is_error or not plan_ok(
                refreshed.data, LAB_ID, LAB_TITLE, 1, 3
            ):
                emit(success=False, stage="last_gate", reason="Lab count drift before POST")
                return 1

            emit(stage="prepared", lab_plan=LAB_ID, relative_slot="W1 FRI",
                 source_strength_id=SOURCE_ID, blocks=6, sets=14,
                 instructions_chars=len(instructions), write_attempts_allowed=1)
            try:
                response = await http.post(
                    f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{LAB_ID}/workouts/save",
                    headers=_headers(access),
                    json=payload,
                )
            except httpx.RequestError:
                emit(success=False, stage="post", error_code="AMBIGUOUS_POST",
                     retry_allowed=False)
                return 1
            if response.status_code != 200:
                detail = {}
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        issues = data.get("errors")
                        if isinstance(issues, dict):
                            detail = {
                                str(k)[:50]: str(v)[:150]
                                for k, v in list(issues.items())[:5]
                            }
                except (ValueError, TypeError):
                    pass
                emit(success=False, stage="post", http_status=response.status_code,
                     validation=detail, retry_allowed=False)
                return 1

            try:
                body = response.json()
                created = body.get("data") if isinstance(body, dict) else None
                workout_id = str((created or {}).get("id") or payload["id"])
            except (TypeError, ValueError, AttributeError):
                emit(success=False, stage="post", error_code="AMBIGUOUS_REPLY",
                     retry_allowed=False)
                return 1

            check_r = await http.get(
                f"{STRENGTH_API_BASE}/rx/activity/v1/workouts/{workout_id}",
                headers=_headers(access),
            )
            check = (
                check_r.json().get("data") or {}
                if check_r.status_code == 200 else {}
            )
            memberships = await get_plan_strength(http, access, LAB_ID, start)
            plan_after_r = await client.get(f"/plans/v1/plans/{LAB_ID}")
            plan_after = plan_after_r.data if not plan_after_r.is_error else {}
            asm_after_r = await client.get(f"/plans/v1/plans/{ASSEMBLY_ID}")
            asm_after = asm_after_r.data if not asm_after_r.is_error else {}
            membership_found = (
                memberships is not None
                and workout_id in json.dumps(memberships, ensure_ascii=False)
            )
            pass_check = (
                check.get("workoutType") == "StructuredStrength"
                and check.get("title") == PROBE_TITLE
                and (check.get("snapshot") or {}).get("totalSets") == 14
                and membership_found
                and plan_after.get("workoutCount") == 4
                and asm_after.get("workoutCount") == 229
            )
            emit(success=pass_check, one_post_sent=True, lab_plan=LAB_ID,
                 workout_id=workout_id, blocks=len(check.get("blocks") or []),
                 sets=(check.get("snapshot") or {}).get("totalSets"),
                 in_native_lab_list=membership_found,
                 native_lab_list_size=len(memberships) if memberships is not None else None,
                 lab_count_after=plan_after.get("workoutCount"),
                 intermediate_count_after=asm_after.get("workoutCount"),
                 interpretation=(
                     "LAB_SUCCESS: identical six-block structure attaches in sacrificial plan"
                     if pass_check else
                     "LAB_NOT_VERIFIED: stop, investigate before any retry"
                 ),
                 retry_allowed=False)
            return 0 if pass_check else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
