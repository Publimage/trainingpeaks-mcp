"""Scoped writer adapter for a disposable private TrainingPeaks LAB canary only.

Do not expand this allowlist to commercial plans. A platform authorization
refusal remains final for that denied operation; the canary is independent.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.ironman_jobs.plan_patch_batch_core import PlanPatchStop, require
    from scripts.ironman_jobs.tp_plan_readonly_gateway import TrainingPeaksPlanReadGateway
except ModuleNotFoundError:
    from plan_patch_batch_core import PlanPatchStop, require
    from tp_plan_readonly_gateway import TrainingPeaksPlanReadGateway


LAB_ID = 684206
LAB_WORKOUT_ID = 3994992835
LAB_TITLE = "[MCP TEST] Training Plan — Swim Bike Run"


class PrivateLabWriteGateway(TrainingPeaksPlanReadGateway):
    """Explicit 1-workout allowlist, not a generic unrestricted publisher."""

    def __init__(self, client: Any) -> None:
        super().__init__(
            client, LAB_ID, [("2027-06-18", "2027-07-04")],
            expected_owner_id=2116886
        )

    async def put_workout(
        self, plan_id: int, workout_id: int, payload: dict[str, Any]
    ) -> bool:
        require(plan_id == LAB_ID and workout_id == LAB_WORKOUT_ID,
                "LAB_WRITE_TARGET_NOT_ALLOWLISTED")
        plan = await self.get_plan(plan_id)
        require(plan.get("title") == LAB_TITLE and plan.get("isPublic") is False
                and plan.get("workoutCount") == 6,
                "LAB_WRITE_SCOPE_CHANGED")
        original = await self.get_workout(plan_id, workout_id)
        require(original.get("workoutTypeValueId") == 2, "LAB_EXPECTS_BIKE")
        require(payload.get("workoutId") == workout_id, "LAB_PAYLOAD_ID_DRIFT")
        require({k: v for k, v in payload.items() if k != "title"}
                == {k: v for k, v in original.items() if k != "title"},
                "LAB_WRITE_NON_TITLE_MUTATION")
        response = await self.client._request(
            "PUT", f"/plans/v1/plans/{LAB_ID}/workouts/{LAB_WORKOUT_ID}",
            json=payload, _retry_on_401=False
        )
        if response.is_error:
            # Never turn a 403/forbidden endpoint into an automatic retry.
            raise PlanPatchStop(
                "LAB_PROVIDER_WRITE_REFUSED_" + str(response.error_code or "unknown")
            )
        return True
