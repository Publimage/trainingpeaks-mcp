"""Official-connector read-only adapter for plan-scoped workout readback.

Provider writes are deliberately not implemented. This adapter verifies the
live connector's read path independently of any specific workout publication.
"""
from __future__ import annotations

from typing import Any

from scripts.ironman_jobs.plan_patch_batch_core import PlanPatchStop, require


class TrainingPeaksPlanReadGateway:
    def __init__(
        self, client: Any, plan_id: int, windows: list[tuple[str, str]],
        *,
        expected_owner_id: int = 2116886,
    ) -> None:
        require(type(plan_id) is int and plan_id > 0, "INVALID_PLAN_ID")
        require(type(expected_owner_id) is int and expected_owner_id > 0, "OWNER_ID_REQUIRED")
        require(isinstance(windows, list) and 1 <= len(windows) <= 6, "WINDOW_COUNT")
        for start, end in windows:
            require(isinstance(start, str) and isinstance(end, str)
                    and len(start) == 10 and len(end) == 10 and start <= end,
                    "INVALID_WINDOW")
        self.client = client
        self.plan_id = plan_id
        self.windows = list(windows)
        self.expected_owner_id = expected_owner_id

    async def get_owner_id(self) -> int:
        identity = await self.client._get_user_data()
        require(isinstance(identity, dict)
                and identity.get("personId") == self.expected_owner_id,
                "WRONG_COACH_ACCOUNT")
        return int(identity["personId"])

    async def get_plan(self, plan_id: int) -> dict[str, Any]:
        require(plan_id == self.plan_id, "CROSS_PLAN_READ_FORBIDDEN")
        response = await self.client.get(f"/plans/v1/plans/{plan_id}")
        require(not response.is_error and isinstance(response.data, dict),
                "PLAN_READ_FAILED")
        require(response.data.get("planId") == plan_id, "PLAN_ID_DRIFT")
        return response.data

    async def list_workouts(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for start, end in self.windows:
            response = await self.client.get(
                f"/plans/v1/plans/{self.plan_id}/workouts/{start}/{end}"
            )
            require(not response.is_error and isinstance(response.data, list),
                    "WORKOUT_LIST_READ_FAILED")
            for row in response.data:
                require(isinstance(row, dict)
                        and type(row.get("workoutId")) is int, "INVALID_PROVIDER_WORKOUT")
                rows.append(row)
        seen: dict[int, dict[str, Any]] = {}
        for row in rows:
            wid = row["workoutId"]
            if wid in seen:
                require(seen[wid] == row, "INCONSISTENT_WINDOW_OVERLAP")
            seen[wid] = row
        return list(seen.values())

    async def get_workout(self, plan_id: int, workout_id: int) -> dict[str, Any]:
        require(plan_id == self.plan_id, "CROSS_PLAN_READ_FORBIDDEN")
        require(type(workout_id) is int and workout_id > 0, "INVALID_WORKOUT_ID")
        found = [row for row in await self.list_workouts() if row["workoutId"] == workout_id]
        require(len(found) == 1, "WORKOUT_NOT_FOUND_IN_PLAN")
        return found[0]

    async def put_workout(self, plan_id: int, workout_id: int, payload: dict[str, Any]) -> Any:
        raise PlanPatchStop("WRITES_NOT_ENABLED_IN_READONLY_ADAPTER")
