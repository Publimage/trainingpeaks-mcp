"""LAB-only provider writer tests: all fake, zero external writes."""
import asyncio
from types import SimpleNamespace

import pytest

from scripts.ironman_jobs.plan_patch_batch_core import PlanPatchStop, validate_manifest
from scripts.ironman_jobs.plan_patch_private_lab_write_canary_20261018 import (
    CANARY, OLD, LAB_ID, LAB_WORKOUT_ID, manifest
)
from scripts.ironman_jobs.tp_private_lab_write_gateway import PrivateLabWriteGateway


class FakeTP:
    def __init__(self):
        self.posts = []
        self.row = {
            "workoutId": LAB_WORKOUT_ID,
            "workoutTypeValueId": 2,
            "title": OLD,
            "description": "original text",
            "totalTimePlanned": 1.0,
            "structure": {"primaryLengthMetric": "time"},
        }

    async def _get_user_data(self):
        return {"personId": 2116886}

    async def get(self, path):
        if path == "/plans/v1/plans/684206":
            return SimpleNamespace(is_error=False, data={
                "planId": LAB_ID,
                "title": "[MCP TEST] Training Plan — Swim Bike Run",
                "workoutCount": 6,
                "isPublic": False
            })
        if path.startswith("/plans/v1/plans/684206/workouts/"):
            return SimpleNamespace(is_error=False, data=[self.row])
        return SimpleNamespace(is_error=True, data=None)

    async def _request(self, method, path, json=None, _retry_on_401=True):
        self.posts.append((method, path, json, _retry_on_401))
        self.row = json
        return SimpleNamespace(is_error=False, error_code=None)


def run(coro):
    return asyncio.run(coro)


def test_only_lab_title_is_mutable():
    f = FakeTP()
    gw = PrivateLabWriteGateway(f)
    request = dict(f.row, title=CANARY)
    assert run(gw.put_workout(LAB_ID, LAB_WORKOUT_ID, request))
    assert len(f.posts) == 1
    method, path, body, retry = f.posts[0]
    assert method == "PUT"
    assert path.endswith(f"/plans/684206/workouts/{LAB_WORKOUT_ID}")
    assert retry is False
    assert body["description"] == "original text"


def test_no_other_workout_or_non_title_changes():
    f = FakeTP()
    gw = PrivateLabWriteGateway(f)
    with pytest.raises(PlanPatchStop, match="TARGET_NOT_ALLOWLISTED"):
        run(gw.put_workout(LAB_ID, LAB_WORKOUT_ID + 1, dict(f.row)))
    with pytest.raises(PlanPatchStop, match="NON_TITLE_MUTATION"):
        run(gw.put_workout(LAB_ID, LAB_WORKOUT_ID, dict(f.row, description="changed")))
    assert not f.posts


def test_no_write_to_public_lab():
    f = FakeTP()
    original_get = f.get

    async def public_get(path):
        response = await original_get(path)
        if path == "/plans/v1/plans/684206":
            response.data["isPublic"] = True
        return response

    f.get = public_get
    with pytest.raises(PlanPatchStop, match="LAB_WRITE_SCOPE_CHANGED"):
        run(PrivateLabWriteGateway(f).put_workout(LAB_ID, LAB_WORKOUT_ID, dict(f.row)))
    assert not f.posts


def test_denied_provider_write_stops():
    f = FakeTP()

    async def forbidden(*args, **kwargs):
        return SimpleNamespace(is_error=True, error_code="AUTH_INVALID")

    f._request = forbidden
    with pytest.raises(PlanPatchStop, match="LAB_PROVIDER_WRITE_REFUSED"):
        run(PrivateLabWriteGateway(f).put_workout(LAB_ID, LAB_WORKOUT_ID, dict(f.row, title=CANARY)))


def test_restore_is_separate_approved_manifest():
    forward = manifest(OLD, CANARY, "forward")
    reverse = manifest(CANARY, OLD, "restore")
    assert validate_manifest(forward) != validate_manifest(reverse)
    assert forward["scope"] != reverse["scope"]
    assert forward["items"][0]["workout_id"] == LAB_WORKOUT_ID
    assert reverse["items"][0]["after"]["title"] == OLD
