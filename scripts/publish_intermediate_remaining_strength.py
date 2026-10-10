"""Publish the remaining 29 *approved* native Strength Builder sessions to one private TEST Training Plan.

Source: data/intermediate_strength_remaining_29.json, generated from the
Google Drive canonical archive on 2026-10-10. Does not contact Google Drive.

Only --execute permits writes. Exactly one provider POST per item with native
readback; fail closed on any mismatch, network ambiguity, count drift, or
unrecognized source. No automatic retry, no delete, no athlete calendars,
no commercial plans. Date strings serve ONLY as technical relative slots.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools.strength import (
    STRENGTH_API_BASE,
    STRENGTH_TIMEOUT,
    _access,
    _headers,
    tp_batch_add_intermediate_strength,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/intermediate_strength_remaining_29.json"
PLAN_ID = 684602
LAB_ID = 684543
PLAN_TITLE = "[MCP TEST] IRONMAN Intermediate Assembly 24W"
LAB_TITLE = "[MCP TEST] TP Native Strength Plan Route 2026-10-09"
VERIFIED_CANARY = "33973000"
EXPECTED_START = date(2026, 10, 5)
START_COUNT = 230
FINAL_COUNT = 259


def output(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def checked_manifest() -> list[dict[str, Any]]:
    j = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if (
        j.get("schema") != "IRONMAN_NATIVE_STRENGTH_APPROVED_2026_10_10_V1"
        or j.get("plan_id") != PLAN_ID
        or j.get("already_verified_workout_id") != VERIFIED_CANARY
        or j.get("starting_plan_count") != START_COUNT
        or j.get("total_remaining") != 29
    ):
        raise ValueError("Manifest identity mismatched")
    items = j.get("items")
    if not isinstance(items, list) or len(items) != 29:
        raise ValueError("Expected exactly 29 approved sessions")
    uuids: set[str] = set()
    slots: set[tuple[int, str]] = set()
    last_order = None
    valid_days = {"TUE": 1, "WED": 2, "THU": 3, "FRI": 4}
    for x in items:
        w = x.get("week")
        d = x.get("day")
        uid = x.get("uid")
        title = x.get("title")
        ins = x.get("instructions")
        blocks = x.get("blocks")
        if type(w) is not int or not 1 <= w <= 22 or d not in valid_days:
            raise ValueError("Invalid relative week/day")
        if (not isinstance(uid, str)
            or uid != f"IMINT24W-W{w:02d}-{d}-STRENGTH-0{3 if d in ('TUE', 'FRI') else 2}"):
            raise ValueError("Canonical UID mismatch")
        if (
            uid in uuids or (w, d) in slots
            or not isinstance(title, str)
            or not title.startswith(f"IRONMAN | STRENGTH | W{w:02d} {d} | ")
            or not isinstance(ins, str) or not 180 <= len(ins) <= 1000
            or not isinstance(blocks, list) or not 5 <= len(blocks) <= 6
        ):
            raise ValueError("Invalid or duplicated manifest item")
        sets = 0
        for b in blocks:
            if b.get("type") != "SingleExercise" or len(b.get("exercises", [])) != 1:
                raise ValueError("Unexpected Strength block format")
            ex = b["exercises"][0]
            if not isinstance(ex.get("sets"), list) or not ex["sets"]:
                raise ValueError("Missing native prescription")
            sets += len(ex["sets"])
        if not 5 <= sets <= 14:
            raise ValueError("Invalid Strength set count")
        order = (w - 1) * 7 + valid_days[d]
        if last_order is not None and order <= last_order:
            raise ValueError("Manifest not in relative week/day order")
        last_order = order
        uuids.add(uid)
        slots.add((w, d))
    if "IMINT24W-W01-WED-STRENGTH-02" in uuids:
        raise ValueError("Previously verified canary must not be republished")
    return items


async def preflight() -> tuple[bool, dict[str, Any]]:
    async with TPClient() as client:
        target = await client.get(f"/plans/v1/plans/{PLAN_ID}")
        lab = await client.get(f"/plans/v1/plans/{LAB_ID}")
        if target.is_error or lab.is_error:
            return False, {"error": "PLAN_UNAVAILABLE"}
        p, l = target.data, lab.data
        if (
            not isinstance(p, dict) or not isinstance(l, dict)
            or p.get("planId") != PLAN_ID
            or p.get("title") != PLAN_TITLE
            or p.get("workoutCount") != START_COUNT
            or p.get("weekCount") != 24
            or p.get("price") not in (None, 0)
            or p.get("isPublic") is not False
            or (p.get("startDate") or "")[:10] != EXPECTED_START.isoformat()
            or l.get("planId") != LAB_ID
            or l.get("title") != LAB_TITLE
            or l.get("workoutCount") != 5
            or l.get("weekCount") != 44
        ):
            return False, {
                "error": "PROTECTED_PLAN_DRIFT",
                "target_count": p.get("workoutCount"),
                "target_weeks": p.get("weekCount"),
                "lab_count": l.get("workoutCount"),
                "lab_weeks": l.get("weekCount"),
            }
        try:
            target_person = int(p.get("planPersonId"))
            lab_person = int(l.get("planPersonId"))
            target_owner = int(p.get("ownerPersonId"))
            lab_owner = int(l.get("ownerPersonId"))
        except (TypeError, ValueError):
            return False, {"error": "PLAN_PERSON_MAPPING_UNREADABLE"}
        if (
            target_person <= 0 or lab_person <= 0
            or target_person == lab_person or target_owner <= 0
            or target_owner != lab_owner
        ):
            return False, {"error": "PLAN_PERSON_MAPPING_DRIFT"}
        _, access, error = await _access(client)
        if error or not access:
            return False, {"error": "AUTH_UNAVAILABLE"}
        async with httpx.AsyncClient(timeout=STRENGTH_TIMEOUT) as h:
            url = (
                f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{PLAN_ID}"
                f"/workouts/{EXPECTED_START.isoformat()}/"
                f"{(EXPECTED_START + timedelta(days=8)).isoformat()}"
            )
            try:
                rr = await h.get(url, headers=_headers(access))
                if rr.status_code != 200:
                    return False, {"error": "NATIVE_STRENGTH_LIST_UNAVAILABLE",
                                   "http_status": rr.status_code}
                body = rr.json()
                existing = body.get("data") if isinstance(body, dict) else body
                if not isinstance(existing, list):
                    return False, {"error": "INVALID_NATIVE_LIST_SHAPE"}
                ids = {str(x.get("id") or x.get("workoutId")) for x in existing
                       if isinstance(x, dict)}
                if ids != {VERIFIED_CANARY}:
                    return False, {"error": "UNEXPECTED_EXISTING_NATIVE_STRENGTH",
                                   "count": len(existing)}
                canary = await h.get(
                    f"{STRENGTH_API_BASE}/rx/activity/v1/workouts/{VERIFIED_CANARY}",
                    headers=_headers(access),
                )
                if canary.status_code != 200:
                    return False, {"error": "CANARY_UNREADABLE"}
                x = canary.json().get("data") or {}
                if (
                    x.get("title") != "IRONMAN | STRENGTH | W01 WED | Forza A | Base 35'"
                    or x.get("workoutType") != "StructuredStrength"
                    or int(x.get("calendarId") or 0) != target_person
                    or len(x.get("blocks") or []) != 6
                    or (x.get("snapshot") or {}).get("totalSets") != 14
                ):
                    return False, {"error": "CANARY_NATIVE_MISMATCH"}
            except (httpx.RequestError, ValueError, TypeError):
                return False, {"error": "READBACK_FAILED"}
    return True, {"existing_native_strength": 1, "count": START_COUNT}


async def publish() -> int:
    try:
        items = checked_manifest()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        output({"success": False, "stage": "manifest", "error": str(exc)})
        return 1
    if sys.argv[1:] != ["--execute"]:
        output({"success": True, "dry_run": True, "plan_id": PLAN_ID,
                "sessions_ready": len(items), "write_performed": False})
        return 0

    good, diagnostic = await preflight()
    output({"stage": "preflight", "success": good, **diagnostic})
    if not good:
        return 1

    created: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        expected_count = START_COUNT + i
        dry = await tp_batch_add_intermediate_strength(
            items=[item], expected_plan_count=expected_count, dry_run=True
        )
        if (
            not dry.get("success") or dry.get("write_performed") is not False
            or dry.get("batch_count") != 1
            or dry.get("manifest", [{}])[0].get("uid") != item["uid"]
        ):
            output({"success": False, "stage": "dry_run", "index": i+1,
                    "uid": item["uid"], "expected_count": expected_count,
                    "error_code": dry.get("error_code"), "created_so_far": created,
                    "retry_automatically": False})
            return 1
        try:
            res = await tp_batch_add_intermediate_strength(
                items=[item], expected_plan_count=expected_count, dry_run=False
            )
        except Exception as exc:
            # Even an exception can follow a successful POST: never retry.
            output({"success": False, "stage": "ambiguous_write_exception",
                    "index": i+1, "uid": item["uid"],
                    "error_type": type(exc).__name__, "created_so_far": created,
                    "retry_automatically": False})
            return 1
        if not res.get("success"):
            output({"success": False, "stage": "write_or_readback",
                    "index": i+1, "uid": item["uid"],
                    "error_code": res.get("error_code"),
                    "http_status": res.get("http_status"),
                    "provider_validation": res.get("provider_validation"),
                    "unverified_workout_id": res.get("unverified_workout_id"),
                    "count_after": res.get("plan_count"),
                    "created_so_far": created, "retry_automatically": False})
            return 1
        new = res.get("workouts", [])
        if not isinstance(new, list) or len(new) != 1 or (
            new[0].get("uid") != item["uid"]
        ):
            output({"success": False, "stage": "ambiguous_success_shape",
                    "index": i+1, "uid": item["uid"], "created_so_far": created,
                    "retry_automatically": False})
            return 1
        record = {"uid": item["uid"], "workout_id": new[0].get("workout_id")}
        created.append(record)
        output({"stage": "verified", "index": i+1, "total": 29,
                "uid": item["uid"], "workout_id": record["workout_id"],
                "expected_count_after": expected_count+1})

    async with TPClient() as client:
        p = await client.get(f"/plans/v1/plans/{PLAN_ID}")
        lab = await client.get(f"/plans/v1/plans/{LAB_ID}")
        pc = p.data.get("workoutCount") if not p.is_error else None
        lc = lab.data.get("workoutCount") if not lab.is_error else None
    complete = pc == FINAL_COUNT and lc == 5 and len(created) == 29
    output({"success": complete, "stage": "final",
            "plan_id": PLAN_ID, "training_plan_count": pc,
            "expected_training_plan_count": FINAL_COUNT,
            "strength_verified": 1 + len(created), "lab_count": lc,
            "created": created, "retry_automatically": False})
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(publish()))
