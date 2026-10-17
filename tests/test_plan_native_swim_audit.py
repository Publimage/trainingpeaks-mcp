"""Read-only QA: full swim structure only appears for private lab plans."""

from datetime import date
from unittest.mock import AsyncMock
import pytest

from tp_mcp.tools import plans


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def provider_stub(monkeypatch):
    structure = {
        "primaryLengthMetric": "distance",
        "structure": [{
            "type": "repetition",
            "length": {"value": 6, "unit": "repetition"},
            "steps": [
                {"name": "250m swim", "length": {"value": 250, "unit": "meter"}},
                {"name": "Recover", "length": {"value": 20, "unit": "second"}},
            ],
        }],
    }
    workouts = [{
        "workoutId": 3995120063,
        "workoutDay": "2027-01-12T00:00:00",
        "workoutTypeValueId": 1,
        "title": "[MCP TEST] 6x250 swim",
        "description": "Private lab workout",
        "totalTimePlanned": 50 / 60,
        "distancePlanned": 2700,
        "structure": structure,
    }]
    async def fake_fetch(client, plan_id):
        return date(2027, 1, 4), workouts
    monkeypatch.setattr(plans, "TPClient", FakeClient)
    monkeypatch.setattr(plans, "_fetch_plan_workouts", fake_fetch)
    monkeypatch.setattr(plans, "tp_get_training_plan_notes",
                        AsyncMock(return_value={"notes": [], "count": 0}))
    return structure


@pytest.mark.asyncio
async def test_private_lab_exposes_native_steps(provider_stub):
    res = await plans.tp_get_training_plan_workouts(684463)
    swim = res["workouts"][0]
    assert swim["native_structure"] == provider_stub
    assert swim["native_structure"]["structure"][0]["steps"][1]["length"] == {
        "value": 20, "unit": "second"
    }
    assert swim["native_distance_planned_m"] == 2700
    assert swim["native_duration_planned_h"] == 50 / 60
    assert swim["distance_km"] == 2.7
    assert swim["duration_min"] == 50


@pytest.mark.asyncio
async def test_commercial_plan_stays_slim(provider_stub):
    res = await plans.tp_get_training_plan_workouts(679801)
    swim = res["workouts"][0]
    assert swim["has_structure"] is True
    assert "native_structure" not in swim
    assert "native_distance_planned_m" not in swim
    assert "native_duration_planned_h" not in swim
