"""Generic TrainingPeaks provider READ gateway for the unified changeset engine.

One resource-type adapter, independent of plan/workout/note IDs.
Real provider READ ONLY. Writer methods intentionally not installed here:
before a first public write, each type must reuse and pass its own reviewed
Proven Path plus an authorized canary. Never use the gateway to evade denial.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, cast

from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    Adapter, ChangeStop, SecurityDenied, OWNER, VALID_KINDS
)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ChangeStop(code)


def plan_windows(p: dict[str, Any]) -> list[tuple[str, str]]:
    require(type(p.get("weekCount")) is int and 1 <= p["weekCount"] <= 52,
            "INVALID_PLAN_WEEKS")
    try:
        start = date.fromisoformat(str(p["startDate"])[:10])
    except (ValueError, TypeError, KeyError) as exc:
        raise ChangeStop("INVALID_PLAN_START") from exc
    result = []
    for offset in range(0, p["weekCount"], 8):
        first = start + timedelta(weeks=offset)
        last = start + timedelta(days=min(p["weekCount"], offset + 8)*7-1)
        result.append((first.isoformat(), last.isoformat()))
    return result


async def read_trainingpeaks_item(spec: dict[str, Any]) -> dict[str, Any]:
    """Read current native provider object and verify coach + container ownership."""
    from tp_mcp.client import TPClient

    kind = spec["kind"]
    target = spec["target"]
    require(kind in VALID_KINDS, "ADAPTER_KIND_NOT_SUPPORTED")
    require(target["owner_id"] == OWNER and target["provider"] == "trainingpeaks",
            "PROVIDER_OWNER_MISMATCH")
    container_id = target["container_id"]
    resource_id = target["resource_id"]

    async with TPClient() as c:
        identity = await c._get_user_data()
        require(isinstance(identity, dict) and identity.get("personId") == OWNER,
                "COACH_ACCOUNT_MISMATCH")
        if kind.startswith("library."):
            require(target["container_kind"] == "workout_library", "NOT_LIBRARY_TARGET")
            r = await c.get(f"/exerciselibrary/v2/libraries/{container_id}/items")
            require(not r.is_error and isinstance(r.data, list), "LIBRARY_READ_FAILED")
            found = [x for x in cast(list[dict[str, Any]], r.data)
                     if x.get("exerciseLibraryItemId", x.get("id")) == resource_id]
            require(len(found) == 1, "LIBRARY_ITEM_NOT_UNIQUE")
            return found[0]

        require(target["container_kind"] == "training_plan", "NOT_PLAN_TARGET")
        response = await c.get(f"/plans/v1/plans/{container_id}")
        require(not response.is_error and isinstance(response.data, dict),
                "TRAINING_PLAN_READ_FAILED")
        plan = cast(dict[str, Any], response.data)
        require(plan.get("planId") == container_id
                and plan.get("ownerPersonId") == OWNER
                and type(plan.get("planPersonId")) is int, "TRAINING_PLAN_OWNER_DRIFT")

        if kind == "plan.strength.relocate":
            import httpx
            from tp_mcp.tools.strength import _access, _headers, STRENGTH_API_BASE
            _, token, error = await _access(c)
            require(not error and token, "STRENGTH_AUTH_FAILED")
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as h:
                strength_response = await h.get(
                    STRENGTH_API_BASE+f"/rx/activity/v1/workouts/{resource_id}",
                    headers=_headers(token)
                )
                require(strength_response.status_code == 200, "STRENGTH_READ_FAILED")
                payload = strength_response.json()
                obj = payload.get("data") if isinstance(payload, dict) else payload
                require(isinstance(obj, dict) and obj.get("id") == resource_id
                        and obj.get("calendarId") == plan["planPersonId"]
                        and obj.get("workoutType") == "StructuredStrength",
                        "STRENGTH_ITEM_SCOPE_MISMATCH")
                return cast(dict[str, Any], obj)

        windows = plan_windows(plan)
        if kind == "plan.workout.patch":
            workouts: dict[int, dict[str, Any]] = {}
            for first, last in windows:
                r = await c.get(
                    f"/plans/v1/plans/{container_id}/workouts/{first}/{last}"
                )
                require(not r.is_error and isinstance(r.data, list),
                        "WORKOUT_WINDOW_FAILED")
                for row in cast(list[dict[str, Any]], r.data):
                    wid = row.get("workoutId")
                    require(type(wid) is int, "INVALID_WORKOUT_ROW")
                    if wid in workouts:
                        require(workouts[cast(int, wid)] == row, "WORKOUT_WINDOW_INCONSISTENCY")
                    workouts[cast(int, wid)] = row
            require(resource_id in workouts, "WORKOUT_NOT_IN_TARGET_PLAN")
            return workouts[resource_id]

        # All three native note variants need the same complete note readback;
        # include attachments so unrelated PDFs are fingerprint-protected.
        if kind in ("plan.note.patch", "plan.note.attachment.add",
                    "plan.note.attachment.retire"):
            first, last = windows[0][0], windows[-1][1]
            r = await c.get(f"/plans/v1/plans/{container_id}/calendarNote/{first}/{last}")
            require(not r.is_error and isinstance(r.data, list),
                    "PLAN_NOTES_READ_FAILED")
            found = [x for x in cast(list[dict[str, Any]], r.data) if x.get("id") == resource_id]
            require(len(found) == 1, "NOTE_NOT_IN_TARGET_PLAN")
            note = found[0]
            require(note.get("planId") == container_id, "NOTE_PLAN_ID_DRIFT")
            return note
        raise ChangeStop("RESOURCE_TYPE_NOT_IMPLEMENTED")


class TrainingPeaksReadOnlyAdapter:
    def read(self, spec: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(read_trainingpeaks_item(spec))

    def apply(self, spec: dict[str, Any]) -> None:
        # This is an explicit capability restriction, not a recoverable
        # transport error. No generic write entrypoint is exposed yet.
        raise SecurityDenied("PROVIDER_WRITER_NOT_APPROVED")


def create_read_registry(transport: str = "local") -> dict[str, Any]:
    """One typed read registry, local on TP host or private VPC on Prefect host."""
    if transport == "local":
        adapter: Adapter = TrainingPeaksReadOnlyAdapter()
    elif transport == "private_bridge":
        from tp_mcp.unified_read_bridge import PrivateBridgeReadAdapter
        adapter = PrivateBridgeReadAdapter()
    else:
        raise ChangeStop("UNIFIED_UNSUPPORTED_READ_TRANSPORT")
    registry: dict[str, Adapter] = {kind: adapter for kind in VALID_KINDS}
    # Reuse the SAME read transport for two reviewed field/attachment
    # validators; no provider writers are installed by this registry.
    from scripts.ironman_jobs.ironman_unified_note_pdf_adapter import (
        ReviewedNotePdfRetireAdapter,
    )
    from scripts.ironman_jobs.ironman_unified_plan_workout_adapter import (
        ReviewedClassicPlanPatchAdapter,
    )
    registry["plan.note.attachment.retire"] = ReviewedNotePdfRetireAdapter(reader=adapter)
    registry["plan.workout.patch"] = ReviewedClassicPlanPatchAdapter(reader=adapter)
    return registry
