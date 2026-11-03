"""Beginner 679801 native Strength Builder plan writers.

Two narrowly-scoped tools:
1) create native StructuredStrength twins in batches of <=8;
2) delete corresponding classic Strength sources only after native twin readback.

No athlete calendar writes, no other plans, no library writes.
"""
from __future__ import annotations

from datetime import date as dt
from datetime import timedelta
from typing import Any

import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools.strength import (
    STRENGTH_API_BASE,
    STRENGTH_TIMEOUT,
    _access,
    _build_payload,
    _err,
    _headers,
    _validate_blocks,
)

PLAN_ID = 679801
PLAN_TITLE = (
    "ALBERTO FAZI ENDURANCE | First Ironman | 24 settimane | "
    "Beginner | Smart Start incluso | Italiano"
)
PLAN_START = "2026-09-21"
OWNER_ID = 2116886
SOURCE_IDS = {
    3978611861, 3978611904, 3978611883, 3978611911, 3978611902, 3978611865,
    3978611892, 3978611927, 3978612069, 3978611975, 3978611992, 3978612084,
    3978612013, 3978611928, 3978612064, 3978611980, 3978612004, 3978611989,
    3978611990, 3978611991, 3978611999, 3978611959, 3978612071, 3978611979,
    3978612092, 3978611983, 3978612073, 3978612076, 3978612090, 3978612133,
    3978612027, 3978612031, 3978612042, 3978612100, 3978611945, 3978611956,
}


async def _plan(client: TPClient) -> dict[str, Any] | None:
    response = await client.get(f"/plans/v1/plans/{PLAN_ID}")
    if response.is_error or not isinstance(response.data, dict):
        return None
    return response.data


def _plan_ok(plan: dict[str, Any], expected_count: int) -> bool:
    return (
        plan.get("planId") == PLAN_ID
        and (plan.get("title") or "").strip() == PLAN_TITLE
        and (plan.get("startDate") or "")[:10] == PLAN_START
        and plan.get("weekCount") == 24
        and plan.get("isPublic") is True
        and plan.get("workoutCount") == expected_count
        and plan.get("ownerPersonId") == OWNER_ID
    )


async def _classic_range(client: TPClient) -> list[dict[str, Any]]:
    end = (dt.fromisoformat(PLAN_START) + timedelta(weeks=24, days=2)).isoformat()
    response = await client.get(
        f"/plans/v1/plans/{PLAN_ID}/workouts/{PLAN_START}/{end}"
    )
    if response.is_error or not isinstance(response.data, list):
        raise RuntimeError("CLASSIC_PLAN_READ_FAILED")
    return response.data


async def _native_range(
    http: httpx.AsyncClient,
    access: str,
) -> list[dict[str, Any]]:
    end = (dt.fromisoformat(PLAN_START) + timedelta(weeks=24, days=2)).isoformat()
    response = await http.get(
        (
            f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{PLAN_ID}/workouts/"
            f"{PLAN_START}/{end}"
        ),
        headers=_headers(access),
    )
    if response.status_code != 200:
        raise RuntimeError("NATIVE_PLAN_READ_FAILED")
    data = response.json()
    data = data.get("data") if isinstance(data, dict) else data
    if not isinstance(data, list):
        raise RuntimeError("NATIVE_PLAN_SHAPE")
    return data


def _native_key(item: dict[str, Any]) -> tuple[str, str]:
    return (
        (item.get("title") or "").strip(),
        str(item.get("prescribedDate") or "")[:10],
    )


async def tp_batch_add_beginner_strength(
    items: list[dict[str, Any]],
    expected_plan_count: int,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Create 1-8 native StructuredStrength twins in public Beginner 679801 only."""
    if type(dry_run) is not bool or type(expected_plan_count) is not int:
        return _err(
            "VALIDATION_ERROR",
            "Require boolean dry_run and integer expected_plan_count.",
        )
    if not isinstance(items, list) or not 1 <= len(items) <= 8:
        return _err("VALIDATION_ERROR", "Require 1-8 items.")

    manifest: list[dict[str, Any]] = []
    seen: set[tuple[int, str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            return _err("VALIDATION_ERROR", "Each item must be an object.")
        source_id = item.get("source_workout_id")
        week = item.get("week")
        day = item.get("day")
        title = item.get("title")
        instructions = item.get("instructions")
        blocks = item.get("blocks")
        if (
            type(source_id) is not int
            or source_id not in SOURCE_IDS
            or type(week) is not int
            or not 1 <= week <= 23
            or type(day) is not int
            or not 0 <= day <= 6
            or not isinstance(title, str)
            or len(title) < 8
            or not isinstance(instructions, str)
            or len(instructions) < 100
        ):
            return _err(
                "VALIDATION_ERROR",
                f"Invalid item identity for {source_id}.",
            )
        invalid = _validate_blocks(blocks)
        if invalid:
            return _err("VALIDATION_ERROR", f"{source_id}: {invalid}")
        date = (
            dt.fromisoformat(PLAN_START)
            + timedelta(days=(week - 1) * 7 + day)
        ).isoformat()
        signature = (source_id, date, title)
        if signature in seen:
            return _err("VALIDATION_ERROR", "Duplicate item.")
        seen.add(signature)
        set_counts: list[int] = [
            len(exercise["sets"]) for block in blocks for exercise in block["exercises"]
        ]
        total_sets = sum(set_counts)
        manifest.append(
            {
                "source_id": source_id,
                "date": date,
                "title": title,
                "instructions": instructions,
                "blocks": blocks,
                "sets": total_sets,
            }
        )

    async with TPClient() as client:
        plan = await _plan(client)
        if not plan or not _plan_ok(plan, expected_plan_count):
            return _err(
                "PROTECTED_RESOURCE",
                "Beginner plan identity/count drift.",
            )
        classic = await _classic_range(client)
        by_id = {
            int(workout.get("workoutId") or 0): workout
            for workout in classic
        }
        for target in manifest:
            workout = by_id.get(target["source_id"])
            if (
                not workout
                or workout.get("workoutTypeValueId") != 9
                or workout.get("structure") is not None
            ):
                return _err(
                    "SOURCE_DRIFT",
                    f"Classic Strength source drift: {target['source_id']}",
                )
            if str(workout.get("workoutDay") or "")[:10] != target["date"]:
                return _err("SOURCE_DATE_DRIFT", str(target["source_id"]))

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "plan_id": PLAN_ID,
                "batch_count": len(manifest),
                "expected_plan_count": expected_plan_count,
                "manifest": [
                    {
                        "source_workout_id": target["source_id"],
                        "date": target["date"],
                        "title": target["title"],
                        "sets": target["sets"],
                    }
                    for target in manifest
                ],
                "write_performed": False,
            }

        _, access, error = await _access(client)
        if error:
            return error
        try:
            calendar_id = int(plan.get("planPersonId"))
        except (TypeError, ValueError):
            calendar_id = 0
        if calendar_id <= 0:
            return _err(
                "PLAN_PERSON_UNAVAILABLE",
                "Beginner planPersonId unavailable.",
            )

        saved: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=STRENGTH_TIMEOUT) as http:
            for target in manifest:
                fresh = await _plan(client)
                if (
                    not fresh
                    or fresh.get("workoutCount")
                    != expected_plan_count + len(saved)
                ):
                    return {
                        "success": False,
                        "error_code": "PLAN_DRIFT",
                        "partial_writes": saved,
                    }

                current = await _native_range(http, access)
                if any(
                    _native_key(item) == (target["title"], target["date"])
                    for item in current
                ):
                    return {
                        "success": False,
                        "error_code": "ALREADY_EXISTS_IN_TARGET",
                        "partial_writes": saved,
                        "source_workout_id": target["source_id"],
                    }

                payload = _build_payload(
                    calendar_id,
                    target["date"],
                    target["title"],
                    target["blocks"],
                    target["instructions"],
                )
                try:
                    response = await http.post(
                        (
                            f"{STRENGTH_API_BASE}/rx/activity/v1/plans/"
                            f"{PLAN_ID}/workouts/save"
                        ),
                        headers=_headers(access),
                        json=payload,
                    )
                except httpx.RequestError:
                    after = await _native_range(http, access)
                    matches = [
                        item
                        for item in after
                        if _native_key(item)
                        == (target["title"], target["date"])
                    ]
                    if len(matches) == 1:
                        native_id = str(
                            matches[0].get("id")
                            or matches[0].get("workoutId")
                        )
                        saved.append(
                            {
                                "source_workout_id": target["source_id"],
                                "workout_id": native_id,
                                "title": target["title"],
                                "date": target["date"],
                            }
                        )
                        continue
                    return {
                        "success": False,
                        "error_code": "AMBIGUOUS_POST",
                        "partial_writes": saved,
                        "never_retry_without_readback": True,
                    }

                if response.status_code != 200:
                    return {
                        "success": False,
                        "error_code": "PROVIDER_REJECTED",
                        "http_status": response.status_code,
                        "partial_writes": saved,
                    }

                body = response.json().get("data") or {}
                native_id = str(body.get("id") or payload["id"])
                detail = await http.get(
                    (
                        f"{STRENGTH_API_BASE}/rx/activity/v1/workouts/"
                        f"{native_id}"
                    ),
                    headers=_headers(access),
                )
                after = await _native_range(http, access)
                refreshed = await _plan(client)
                if detail.status_code != 200 or not refreshed:
                    return {
                        "success": False,
                        "error_code": "READBACK_UNAVAILABLE",
                        "partial_writes": saved,
                    }

                native = detail.json().get("data") or {}
                member = any(
                    str(item.get("id") or item.get("workoutId")) == native_id
                    for item in after
                )
                videos = all(
                    (prescription.get("exercise") or {}).get("videoUrl")
                    for block in native.get("blocks") or []
                    for prescription in block.get("prescriptions") or []
                )
                if (
                    native.get("workoutType") != "StructuredStrength"
                    or native.get("title") != target["title"]
                    or str(native.get("prescribedDate") or "")[:10]
                    != target["date"]
                    or native.get("calendarId") != calendar_id
                    or (native.get("snapshot") or {}).get("totalSets")
                    != target["sets"]
                    or not member
                    or not videos
                    or refreshed.get("workoutCount")
                    != expected_plan_count + len(saved) + 1
                ):
                    return {
                        "success": False,
                        "error_code": "READBACK_MISMATCH",
                        "partial_writes": saved,
                        "unverified_workout_id": native_id,
                    }

                saved.append(
                    {
                        "source_workout_id": target["source_id"],
                        "workout_id": native_id,
                        "title": target["title"],
                        "date": target["date"],
                        "sets": target["sets"],
                    }
                )

        return {
            "success": True,
            "dry_run": False,
            "plan_id": PLAN_ID,
            "written": len(saved),
            "workouts": saved,
            "count_after": expected_plan_count + len(saved),
        }


async def tp_batch_delete_beginner_classic_strength(
    items: list[dict[str, Any]],
    expected_plan_count: int,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Delete 1-8 exact classic Beginner Strength sources after native twins exist."""
    if type(dry_run) is not bool or type(expected_plan_count) is not int:
        return _err(
            "VALIDATION_ERROR",
            "Require boolean dry_run and integer expected_plan_count.",
        )
    if not isinstance(items, list) or not 1 <= len(items) <= 8:
        return _err("VALIDATION_ERROR", "Require 1-8 items.")

    manifest: list[dict[str, Any]] = []
    for item in items:
        source_id = item.get("source_workout_id") if isinstance(item, dict) else None
        title = item.get("native_title") if isinstance(item, dict) else None
        date = item.get("date") if isinstance(item, dict) else None
        if (
            type(source_id) is not int
            or source_id not in SOURCE_IDS
            or not isinstance(title, str)
            or not isinstance(date, str)
        ):
            return _err("VALIDATION_ERROR", "Invalid delete item.")
        manifest.append(
            {
                "source_id": source_id,
                "title": title,
                "date": date[:10],
            }
        )

    async with TPClient() as client:
        plan = await _plan(client)
        if not plan or not _plan_ok(plan, expected_plan_count):
            return _err(
                "PROTECTED_RESOURCE",
                "Beginner plan identity/count drift.",
            )
        _, access, error = await _access(client)
        if error:
            return error

        deleted: list[int] = []
        async with httpx.AsyncClient(timeout=STRENGTH_TIMEOUT) as http:
            for target in manifest:
                classic = await _classic_range(client)
                by_id = {
                    int(workout.get("workoutId") or 0): workout
                    for workout in classic
                }
                source = by_id.get(target["source_id"])
                if source is None:
                    return {
                        "success": False,
                        "error_code": "SOURCE_ALREADY_MISSING",
                        "partial_deletes": deleted,
                    }
                if (
                    source.get("workoutTypeValueId") != 9
                    or source.get("structure") is not None
                    or str(source.get("workoutDay") or "")[:10]
                    != target["date"]
                ):
                    return {
                        "success": False,
                        "error_code": "SOURCE_DRIFT",
                        "partial_deletes": deleted,
                    }

                native = await _native_range(http, access)
                twins = [
                    item
                    for item in native
                    if _native_key(item)
                    == (target["title"], target["date"])
                ]
                if len(twins) != 1:
                    return {
                        "success": False,
                        "error_code": "NATIVE_TWIN_NOT_EXACT",
                        "partial_deletes": deleted,
                    }
                if dry_run:
                    continue

                await client._request(
                    "DELETE",
                    (
                        f"/plans/v1/plans/{PLAN_ID}/workouts/"
                        f"{target['source_id']}"
                    ),
                    _retry_on_401=False,
                )
                after = await _classic_range(client)
                if any(
                    int(workout.get("workoutId") or 0)
                    == target["source_id"]
                    for workout in after
                ):
                    return {
                        "success": False,
                        "error_code": "DELETE_UNVERIFIED",
                        "partial_deletes": deleted,
                        "never_retry_without_readback": True,
                    }

                native_after = await _native_range(http, access)
                if (
                    len(
                        [
                            item
                            for item in native_after
                            if _native_key(item)
                            == (target["title"], target["date"])
                        ]
                    )
                    != 1
                ):
                    return {
                        "success": False,
                        "error_code": "NATIVE_TWIN_LOST",
                        "partial_deletes": deleted,
                    }
                deleted.append(target["source_id"])

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "plan_id": PLAN_ID,
                "batch_count": len(manifest),
                "write_performed": False,
            }
        final = await _plan(client)
        return {
            "success": True,
            "dry_run": False,
            "plan_id": PLAN_ID,
            "deleted": len(deleted),
            "source_workout_ids": deleted,
            "count_after": final.get("workoutCount") if final else None,
        }
