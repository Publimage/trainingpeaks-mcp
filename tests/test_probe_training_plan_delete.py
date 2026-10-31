"""Mock-only safety checks for the disposable Training Plan DELETE probe.

Never contacts TrainingPeaks. The real-world provider test is opt-in via the
local script's --execute flag and only works on a disposable private plan.
"""
from unittest.mock import AsyncMock

import pytest

from scripts import probe_training_plan_delete as probe
from tp_mcp.client.http import APIResponse


def test_valid_plan_workout_ids_must_be_unique_and_positive():
    assert probe._workout_id({"workoutId": 888000}) == 888000
    assert probe._workout_id({"planWorkoutId": 888000, "id": 888000}) == 888000
    assert probe._workout_id({"workoutId": 888000, "id": 777000}) is None
    assert probe._workout_id({"workoutId": True}) is None
    assert probe._workout_id({"workoutId": -1}) is None


def test_disposable_cards_refuse_wrong_titles_types_dates_and_duplicates():
    monday = {
        "workoutId": 101,
        "workoutDay": probe.DAYS[0].isoformat() + "T00:00:00",
        "title": probe.LAB_TEMPLATE_TITLE,
        "workoutTypeValueId": 100,
        "structure": None,
        "totalTimePlanned": 1 / 60,
    }
    assert probe._cards_by_day([monday], (probe.DAYS[0],)) == {
        probe.DAYS[0].isoformat(): 101,
    }
    with pytest.raises(probe.ProbeStopped):
        probe._cards_by_day([{**monday, "workoutTypeValueId": 2}], (probe.DAYS[0],))
    with pytest.raises(probe.ProbeStopped):
        probe._cards_by_day([{**monday, "title": "Real training"}], (probe.DAYS[0],))
    with pytest.raises(probe.ProbeStopped):
        probe._cards_by_day([monday, monday], probe.DAYS[:2])


@pytest.mark.asyncio
async def test_delete_once_blocks_every_protected_plan_without_network():
    client = AsyncMock()
    for protected in probe.PROTECTED_PLAN_IDS:
        with pytest.raises(probe.ProbeStopped):
            await probe._delete_once(client, protected, 889000, "Protected")
    client._request.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_once_uses_only_exact_plan_route_and_disables_auto_retry():
    client = AsyncMock()
    client._request.return_value = APIResponse(success=True, data=None)
    path = await probe._delete_once(client, 888000, 889000, "Disposable")
    assert path == "/plans/v1/plans/888000/workouts/889000"
    client._request.assert_awaited_once_with(
        "DELETE", path, _retry_on_401=False,
    )


@pytest.mark.asyncio
async def test_delete_error_never_retries():
    client = AsyncMock()
    client._request.return_value = APIResponse(success=False)
    with pytest.raises(probe.ProbeStopped, match="Do NOT retry"):
        await probe._delete_once(client, 888000, 889000, "Disposable")
    client._request.assert_awaited_once()
