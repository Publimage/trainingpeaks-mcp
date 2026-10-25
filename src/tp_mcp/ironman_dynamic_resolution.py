"""One request -> dynamic, provider-verified TrainingPeaks target.

The five reader functions are injected to keep this policy independent of the
network and of any historical plan ID. No operation here can publish or delete.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Awaitable, Callable

from tp_mcp.ironman_dynamic_identity import (
    TargetStop, _positive_id, require_new_name_absent,
    resolve_plan_workout, select_live_item,
)

OWNER = 2116886
Reader = Callable[..., Awaitable[dict[str, Any]]]


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    if type(payload) is not dict or payload.get("isError"):
        raise TargetStop("PROVIDER_READ_FAILED")
    items = payload.get(key)
    if type(items) is not list:
        raise TargetStop("PROVIDER_INVENTORY_INVALID")
    return items


def _date_window(start: str | None, end: str | None) -> None:
    if type(start) is not str or type(end) is not str:
        raise TargetStop("ATHLETE_WORKOUT_DATE_WINDOW_REQUIRED")
    try:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise TargetStop("ATHLETE_WORKOUT_DATE_INVALID") from exc
    if b < a or (b - a).days >= 90:
        raise TargetStop("ATHLETE_WORKOUT_DATE_RANGE_INVALID")


async def resolve_live_request(
    kind: str, query: str | int, *, coach_id: int,
    read_plans: Reader, read_athletes: Reader,
    read_libraries: Reader, read_plan_workouts: Reader,
    read_athlete_workouts: Reader,
    plan: str | int | None = None,
    athlete: str | int | None = None,
    week: int | None = None, weekday: int | None = None,
    start_date: str | None = None, end_date: str | None = None,
) -> dict[str, Any]:
    """Live discovery only. The eventual WRITE gate is separate and mandatory."""
    if type(coach_id) is not int or coach_id != OWNER:
        raise TargetStop("ACCOUNT_MISMATCH")
    if kind not in {"training_plan", "new_training_plan", "athlete",
                    "workout_library", "new_workout_library", "plan_workout",
                    "athlete_workout"}:
        raise TargetStop("TARGET_KIND_UNSUPPORTED")
    if kind in {"training_plan", "new_training_plan", "plan_workout"}:
        plans = _rows(await read_plans(), "plans")
        if kind == "new_training_plan":
            identity = require_new_name_absent(plans, query, id_field="plan_id",
                                               title_field="title", scope="training_plan")
            return {**identity, "owner_id": OWNER, "publication_authorized": False}
        target_query = plan if kind == "plan_workout" else query
        plan_binding = select_live_item(plans, target_query, id_field="plan_id",
                                        title_field="title", scope="training_plan")
        plan_id = plan_binding["record"]["plan_id"]
        if kind == "training_plan":
            return {"kind": kind, "target": {"provider": "trainingpeaks",
                    "owner_id": OWNER, "container_kind": "training_plan",
                    "container_id": plan_id}, "plan_title": plan_binding["record"]["title"],
                    "match": plan_binding["match"], "read_only": True,
                    "publication_authorized": False}
        result = await read_plan_workouts(plan_id)
        if type(result) is not dict or result.get("plan_id") != plan_id:
            raise TargetStop("PLAN_READBACK_SCOPE_MISMATCH")
        rows = _rows(result, "workouts")
        workout = resolve_plan_workout(rows, query, plan_id=plan_id,
                                       week=week, weekday=weekday)
        return {"kind": kind, "target": {**workout["target"], "owner_id": OWNER},
                "plan_title": plan_binding["record"]["title"],
                "workout": workout["record"], "match": workout["match"],
                "read_only": True, "publication_authorized": False}
    if kind in {"workout_library", "new_workout_library"}:
        libraries = _rows(await read_libraries(), "libraries")
        if kind == "new_workout_library":
            identity = require_new_name_absent(libraries, query, id_field="id",
                                               title_field="name", scope="workout_library")
            return {**identity, "owner_id": OWNER, "publication_authorized": False}
        binding = select_live_item(libraries, query, id_field="id",
                                   title_field="name", scope="workout_library")
        owner = binding["record"].get("owner_id")
        if not _positive_id(owner):
            raise TargetStop("LIBRARY_OWNER_UNVERIFIABLE")
        return {"kind": kind, "target": {"provider": "trainingpeaks",
                "owner_id": owner, "container_kind": "workout_library",
                "container_id": binding["record"]["id"]},
                "name": binding["record"]["name"],
                "is_coach_owned": owner == OWNER, "match": binding["match"],
                "read_only": True, "publication_authorized": False}
    roster = _rows(await read_athletes(), "athletes")
    athlete_binding = select_live_item(roster,
                  athlete if kind == "athlete_workout" else query,
                  id_field="athlete_id", title_field="name", scope="athlete")
    athlete_id = athlete_binding["record"]["athlete_id"]
    if kind == "athlete":
        return {"kind": kind, "target": {"provider": "trainingpeaks",
                "coach_id": OWNER, "athlete_id": athlete_id},
                "athlete_name": athlete_binding["record"]["name"],
                "match": athlete_binding["match"], "read_only": True,
                "publication_authorized": False}
    _date_window(start_date, end_date)
    result = await read_athlete_workouts(athlete_id, start_date, end_date)
    rows = _rows(result, "workouts")
    converted = []
    for r in rows:
        if type(r) is not dict or type(r.get("id")) is not str or not r["id"].isdecimal():
            raise TargetStop("PROVIDER_ID_UNVERIFIABLE")
        converted.append({**r, "workout_id": int(r["id"])})
    binding = select_live_item(converted, query, id_field="workout_id",
                               title_field="title", scope="athlete_workout")
    return {"kind": kind, "target": {"provider": "trainingpeaks",
            "owner_id": OWNER, "container_kind": "athlete_calendar",
            "athlete_id": athlete_id, "resource_id": binding["record"]["workout_id"]},
            "workout": binding["record"],
            "athlete_name": athlete_binding["record"]["name"],
            "match": binding["match"], "read_only": True,
            "publication_authorized": False}
