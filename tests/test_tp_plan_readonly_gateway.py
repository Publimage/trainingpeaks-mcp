"""Dry adapter tests. No credentials or external provider writes."""
import asyncio
from types import SimpleNamespace

import pytest

from scripts.ironman_jobs.plan_patch_batch_core import PlanPatchStop
from scripts.ironman_jobs.tp_plan_readonly_gateway import TrainingPeaksPlanReadGateway


class FakeClient:
    def __init__(self):
        self.calls = []
        self.plan = {"planId": 684206, "workoutCount": 2, "isPublic": False}
        self.rows = [
            {"workoutId": 123, "title": "Swim", "workoutTypeValueId": 1},
            {"workoutId": 124, "title": "Run", "workoutTypeValueId": 3},
        ]

    async def _get_user_data(self):
        return {"personId": 2116886}

    async def get(self, endpoint):
        self.calls.append(endpoint)
        if endpoint == "/plans/v1/plans/684206":
            return SimpleNamespace(is_error=False, data=self.plan)
        if endpoint.startswith("/plans/v1/plans/684206/workouts/"):
            return SimpleNamespace(is_error=False, data=self.rows)
        return SimpleNamespace(is_error=True, data=None)


def run(coro):
    return asyncio.run(coro)


def gw(client=None, windows=None):
    return TrainingPeaksPlanReadGateway(
        client or FakeClient(), 684206, windows or [("2027-06-21", "2027-06-28")]
    )


def test_owner_plan_workout_readback():
    client = FakeClient()
    adapter = gw(client)
    assert run(adapter.get_owner_id()) == 2116886
    assert run(adapter.get_plan(684206))["isPublic"] is False
    assert len(run(adapter.list_workouts())) == 2
    assert run(adapter.get_workout(684206, 123))["title"] == "Swim"
    assert all(x.startswith("/plans/v1/plans/684206") for x in client.calls)


def test_disallow_cross_plan_and_missing_workout():
    adapter = gw()
    with pytest.raises(PlanPatchStop, match="CROSS_PLAN"):
        run(adapter.get_plan(685173))
    with pytest.raises(PlanPatchStop, match="WORKOUT_NOT_FOUND"):
        run(adapter.get_workout(684206, 9999))


def test_adapter_never_publishes():
    adapter = gw()
    with pytest.raises(PlanPatchStop, match="WRITES_NOT_ENABLED"):
        run(adapter.put_workout(684206, 123, {"title": "x"}))


def test_overlap_is_deduplicated_safely():
    adapter = gw(windows=[
        ("2027-06-21", "2027-06-27"),
        ("2027-06-27", "2027-07-03"),
    ])
    assert len(run(adapter.list_workouts())) == 2


def test_owner_is_explicitly_checked():
    client = FakeClient()

    async def wrong_owner():
        return {"personId": 111}

    client._get_user_data = wrong_owner
    with pytest.raises(PlanPatchStop, match="WRONG_COACH"):
        run(gw(client).get_owner_id())
