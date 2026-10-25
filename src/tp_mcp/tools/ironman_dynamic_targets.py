"""Existing TP-MCP host: read-only dynamic target binding for any chat.

Uses already connected provider readers. It never writes or consults an old
GitHub manifest; requested IDs are resolved from the current provider account.
"""
from __future__ import annotations

from typing import Any

from tp_mcp.client import TPClient
from tp_mcp.client.context import athlete_override
from tp_mcp.ironman_dynamic_identity import TargetStop
from tp_mcp.ironman_dynamic_resolution import resolve_live_request
from tp_mcp.tools.library import tp_get_libraries
from tp_mcp.tools.plans import tp_get_training_plan_workouts, tp_list_training_plans
from tp_mcp.tools.profile import tp_list_athletes
from tp_mcp.tools.workouts import tp_get_workouts


async def _athlete_calendar_workouts(athlete_id: int, start: str, end: str) -> dict[str, Any]:
    token = athlete_override.set(str(athlete_id))
    try:
        return await tp_get_workouts(start, end, "all")
    finally:
        athlete_override.reset(token)


async def tp_ironman_resolve_target(
    kind: str, query: str,
    plan_selector: str | None = None,
    athlete_selector: str | None = None,
    week: int | None = None,
    weekday: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Resolve one current request against live TrainingPeaks identity/roster.

    Does not approve, stage, publish, delete, update, enable permissions,
    read signed files, or send coach credentials to Prefect.
    """
    token = athlete_override.set(None)  # never inherit a different athlete's session
    try:
        async with TPClient() as client:
            account = await client._get_user_data()
        coach_id = account.get("personId") if isinstance(account, dict) else None
        return await resolve_live_request(
            kind, query, coach_id=coach_id,
            read_plans=tp_list_training_plans,
            read_athletes=tp_list_athletes,
            read_libraries=tp_get_libraries,
            read_plan_workouts=tp_get_training_plan_workouts,
            read_athlete_workouts=_athlete_calendar_workouts,
            plan=plan_selector, athlete=athlete_selector,
            week=week, weekday=weekday,
            start_date=start_date, end_date=end_date,
        )
    except TargetStop as exc:
        return {"isError": True, "error_code": exc.code,
                "candidates": exc.candidates, "provider_writes": 0}
    except Exception:
        return {"isError": True, "error_code": "PROVIDER_READ_UNAVAILABLE",
                "provider_writes": 0}
    finally:
        athlete_override.reset(token)
