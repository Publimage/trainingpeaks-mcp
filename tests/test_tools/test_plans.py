"""Tests for training-plan tools (list/get/workouts/apply)."""

from unittest.mock import AsyncMock, patch

import pytest

from tp_mcp.client.http import APIResponse
from tp_mcp.tools.plans import (
    tp_add_training_plan_library_workout,
    tp_add_training_plan_note,
    tp_apply_training_plan,
    tp_create_training_plan,
    tp_get_training_plan,
    tp_get_training_plan_notes,
    tp_get_training_plan_workouts,
    tp_list_training_plans,
)

_DETAIL = {
    "planId": 163992, "title": "Plan 10k  ", "weekCount": 2, "dayCount": 14,
    "workoutCount": 3, "description": "desc", "startDate": "2018-12-17T00:00:00",
    "trainingDurationByWeek": [2.0, 3.0], "trainingDistanceByWeek": [10000.0, 20000.0],
    "plannedWorkoutTypeDurations": [
        {"workoutTypeId": 3, "duration": 5.0, "distance": 40000.0},
        {"workoutTypeId": 7, "duration": 0.0, "distance": 0.0},
    ],
}
# day 1 = period annotation (type 100, skipped on apply), day 2 = structured run,
# day 3 = day off.
_WORKOUTS = [
    {"workoutDay": "2018-12-17T00:00:00", "workoutTypeValueId": 100, "title": "Период: базовый"},
    {"workoutDay": "2018-12-18T00:00:00", "workoutTypeValueId": 3, "title": "Run",
     "description": "easy", "totalTimePlanned": 0.5, "tssPlanned": 26.0,
     "structure": {"structure": [{"x": 1}], "primaryLengthMetric": "duration"}},
    {"workoutDay": "2018-12-19T00:00:00", "workoutTypeValueId": 7, "title": "Выходной"},
]


def _client_with(get_side_effect, post=None, post_side_effect=None, athlete_id=123):
    inst = AsyncMock()
    inst.ensure_athlete_id = AsyncMock(return_value=athlete_id)
    inst.get = AsyncMock(side_effect=get_side_effect)
    if post_side_effect is not None:
        inst.post = AsyncMock(side_effect=post_side_effect)
    else:
        inst.post = AsyncMock(return_value=post or APIResponse(success=True, data={"workoutId": 1}))
    return inst


def _patch(inst):
    p = patch("tp_mcp.tools.plans.TPClient")
    m = p.start()
    m.return_value.__aenter__.return_value = inst
    return p


@pytest.mark.asyncio
async def test_list_slims_records():
    resp = APIResponse(success=True, data=[{
        "planId": 163992, "title": "Plan 10k", "weekCount": 16, "workoutCount": 139,
        "planCategory": 2, "price": 10.0, "isPublic": True, "eventDate": None,
        "trainingDurationByWeek": [2.0, 3.0],
    }])
    inst = _client_with(lambda ep, **k: resp)
    p = _patch(inst)
    try:
        r = await tp_list_training_plans()
    finally:
        p.stop()
    assert r["count"] == 1
    plan = r["plans"][0]
    assert plan["plan_id"] == 163992 and plan["weeks"] == 16 and plan["workouts"] == 139
    assert plan["total_hours"] == 5.0 and plan["price"] == 10.0


@pytest.mark.asyncio
async def test_get_summary_maps_sport_and_weeks():
    inst = _client_with(lambda ep, **k: APIResponse(success=True, data=_DETAIL))
    p = _patch(inst)
    try:
        r = await tp_get_training_plan(163992)
    finally:
        p.stop()
    assert r["title"] == "Plan 10k" and r["weeks"] == 2 and r["day_count"] == 14
    assert r["duration_by_week_h"] == [2.0, 3.0]
    assert r["distance_by_week_km"] == [10.0, 20.0]
    assert {"sport": "Run", "hours": 5.0, "km": 40.0} in r["by_sport"]
    # zero-duration sport (DayOff) is dropped from the breakdown
    assert all(s["sport"] != "DayOff" for s in r["by_sport"])


def _get_router(ep, **k):
    if ep.endswith("/workouts/2018-12-17/2018-12-31"):
        return APIResponse(success=True, data=_WORKOUTS)
    if "/workouts/" in ep:
        return APIResponse(success=True, data=_WORKOUTS)
    return APIResponse(success=True, data=_DETAIL)


@pytest.mark.asyncio
async def test_get_workouts_lays_out_by_week_day():
    inst = _client_with(_get_router)
    p = _patch(inst)
    try:
        r = await tp_get_training_plan_workouts(163992)
    finally:
        p.stop()
    assert r["count"] == 3
    run = next(w for w in r["workouts"] if w["sport"] == "Run")
    assert run["week"] == 1 and run["day"] == 2 and run["has_structure"] is True
    assert run["duration_min"] == 30 and run["tss"] == 26.0
    # period marker surfaces as "Other"
    assert any(w["sport"] == "Other" for w in r["workouts"])


@pytest.mark.asyncio
async def test_synthetic_apply_refuses_unapproved_plan_and_athlete():
    """The previously generic synthetic apply must be TEST-only in the POC."""
    inst = _client_with(_get_router, athlete_id=123)
    p = _patch(inst)
    try:
        result = await tp_apply_training_plan(163992, "2027-09-01")
    finally:
        p.stop()
    assert result["error_code"] == "PROTECTED_RESOURCE"
    inst.get.assert_not_called()
    inst.post.assert_not_called()


def _approved_pilot_workouts():
    return [
        {
            "workoutDay": "2027-06-21T00:00:00",
            "workoutTypeValueId": 1,
            "title": "[MCP TEST] Swim | Tecnica 1200 m - Builder",
            "totalTimePlanned": 0.5,
            "distancePlanned": 1200,
            "structure": {"primaryLengthMetric": "distance"},
        },
        {
            "workoutDay": "2027-06-22T00:00:00",
            "workoutTypeValueId": 2,
            "title": "[MCP TEST] Bike | 3x5' FTP controllato",
            "totalTimePlanned": 0.75,
            "structure": {"primaryLengthMetric": "duration"},
        },
        {
            "workoutDay": "2027-06-23T00:00:00",
            "workoutTypeValueId": 3,
            "title": "[MCP TEST] Run | Progressivo RPE 35'",
            "totalTimePlanned": 35 / 60,
            "description": "Progressivo RPE",
        },
    ]


def _pilot_route(path, **kwargs):
    if path.startswith("/fitness/v6/athletes/941614/workouts/"):
        return APIResponse(success=True, data=[])
    if path.startswith("/plans/v1/plans/684206/workouts/"):
        return APIResponse(success=True, data=_approved_pilot_workouts())
    if path == "/plans/v1/plans/684206":
        return APIResponse(success=True, data={
            "planId": 684206,
            "title": "[MCP TEST] Training Plan — Swim Bike Run",
            "startDate": "2027-06-21T00:00:00",
            "dayCount": 3, "weekCount": 1, "workoutCount": 3,
            "isPublic": False, "price": None,
        })
    raise AssertionError(f"Unexpected pilot endpoint: {path}")


@pytest.mark.asyncio
async def test_synthetic_apply_copies_only_three_pilot_workouts_to_test():
    inst = _client_with(_pilot_route, athlete_id=941614)
    p = _patch(inst)
    try:
        result = await tp_apply_training_plan(684206, "2027-06-21")
    finally:
        p.stop()
    assert result["success"] is True
    assert result["method"] == "synthetic"
    assert result["athlete_id"] == 941614
    assert result["created"] == 3
    assert result["failed"] == 0
    creates = [x.kwargs["json"] for x in inst.post.call_args_list]
    assert len(creates) == 3
    assert [x["workoutDay"] for x in creates] == [
        "2027-06-21T00:00:00",
        "2027-06-22T00:00:00",
        "2027-06-23T00:00:00",
    ]
    assert [x["athleteId"] for x in creates] == [941614] * 3
    assert all(x["title"].startswith("[MCP TEST]") for x in creates)
    assert all("structure" in x for x in creates[:2])
    assert "structure" not in creates[2]
    assert isinstance(creates[0]["structure"], str)


@pytest.mark.asyncio
async def test_synthetic_apply_refuses_occupied_test_sandbox():
    def occupied_route(path, **kwargs):
        if path.startswith("/fitness/v6/athletes/941614/workouts/"):
            return APIResponse(success=True, data=[{"workoutId": 9}])
        return _pilot_route(path, **kwargs)
    inst = _client_with(occupied_route, athlete_id=941614)
    p = _patch(inst)
    try:
        result = await tp_apply_training_plan(684206, "2027-06-21")
    finally:
        p.stop()
    assert result["error_code"] == "ALREADY_EXISTS"
    inst.post.assert_not_called()


@pytest.mark.asyncio
async def test_synthetic_apply_refuses_wrong_test_start_date():
    inst = _client_with(_pilot_route, athlete_id=941614)
    p = _patch(inst)
    try:
        result = await tp_apply_training_plan(684206, "2027-07-01")
    finally:
        p.stop()
    assert result["error_code"] == "PROTECTED_RESOURCE"
    inst.post.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_plan_id_validation():
    r = await tp_get_training_plan(0)
    assert r["isError"] is True and r["error_code"] == "VALIDATION_ERROR"



# Mock-only tests: do not contact TrainingPeaks and do not prove its
# undocumented Training Plan creation endpoint works in the live product.
_TEST_PLAN = {
    "planId": 91919, "title": "[MCP TEST] Integration Plan",
    "startDate": "2027-06-21T00:00:00", "dayCount": 7,
    "weekCount": 1, "isPublic": False, "price": None,
}


@pytest.mark.asyncio
async def test_create_private_test_plan_and_verify_readback():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=[]),
        APIResponse(success=True, data=_TEST_PLAN),
    ])
    client.post = AsyncMock(return_value=APIResponse(
        success=True, data={"planId": 91919},
    ))
    p = _patch(client)
    try:
        result = await tp_create_training_plan(
            title="[MCP TEST] Integration Plan",
            start_date="2027-06-21", week_count=1,
        )
    finally:
        p.stop()
    assert result["success"] is True
    assert result["verified"] is True
    assert client.post.call_args.args[0] == "/plans/v1/plans"
    payload = client.post.call_args.kwargs["json"]
    assert payload["isPublic"] is False
    assert payload["dayCount"] == 7


@pytest.mark.asyncio
async def test_duplicate_plan_refuses_creation():
    client = AsyncMock()
    client.get = AsyncMock(return_value=APIResponse(
        success=True, data=[_TEST_PLAN],
    ))
    client.post = AsyncMock()
    p = _patch(client)
    try:
        result = await tp_create_training_plan(
            title="[MCP TEST] Integration Plan", start_date="2027-06-21",
        )
    finally:
        p.stop()
    assert result["error_code"] == "ALREADY_EXISTS"
    client.post.assert_not_called()


@pytest.mark.asyncio
async def test_plan_create_rejects_non_test_title_before_api_call():
    with patch("tp_mcp.tools.plans.TPClient") as client:
        result = await tp_create_training_plan(
            title="IRONMAN Intermediate", start_date="2027-06-21",
        )
    assert result["error_code"] == "VALIDATION_ERROR"
    client.assert_not_called()


@pytest.mark.asyncio
async def test_add_library_workout_only_to_test_plan():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_TEST_PLAN),
        APIResponse(success=True, data=[{
            "exerciseLibraryItemId": 14935065,
            "itemName": "[MCP TEST] Swim 1200",
        }]),
        APIResponse(success=True, data=[]),  # no existing same-day workout
    ])
    client.post = AsyncMock(return_value=APIResponse(success=True, data={}))
    p = _patch(client)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=91919, library_id="3890637", item_id="14935065",
            workout_date="2027-06-22",
        )
    finally:
        p.stop()
    assert result["success"] is True
    assert result["readback_required"] is True
    assert client.post.call_args.args[0] == (
        "/plans/v1/plans/91919/commands/addworkoutfromlibraryitem"
    )
    assert client.post.call_args.kwargs["json"] == {
        "planId": 91919, "exerciseLibraryItemId": 14935065,
        "workoutDateTime": "2027-06-22",
    }


@pytest.mark.asyncio
async def test_add_workout_refuses_non_test_plan():
    client = AsyncMock()
    client.get = AsyncMock(return_value=APIResponse(
        success=True, data={**_TEST_PLAN, "title": "IRONMAN Intermediate"},
    ))
    client.post = AsyncMock()
    p = _patch(client)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=91919, library_id="3890637", item_id="14935065",
            workout_date="2027-06-22",
        )
    finally:
        p.stop()
    assert result["error_code"] == "PROTECTED_RESOURCE"
    client.post.assert_not_called()
    assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_add_workout_refuses_out_of_range_date():
    client = AsyncMock()
    client.get = AsyncMock(return_value=APIResponse(
        success=True, data=_TEST_PLAN,
    ))
    client.post = AsyncMock()
    p = _patch(client)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=91919, library_id="3890637", item_id="14935065",
            workout_date="2027-07-01",
        )
    finally:
        p.stop()
    assert result["error_code"] == "VALIDATION_ERROR"
    client.post.assert_not_called()


@pytest.mark.asyncio
async def test_plan_note_payload_and_protection():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_TEST_PLAN),
        APIResponse(success=True, data=[]),  # no same-day note
    ])
    client.post = AsyncMock(return_value=APIResponse(success=True, data={}))
    p = _patch(client)
    try:
        result = await tp_add_training_plan_note(
            plan_id=91919, note_date="2027-06-21",
            title="[MCP TEST] Instructions", description="Laboratory only",
        )
    finally:
        p.stop()
    assert result["success"] is True
    assert client.post.call_args.args[0] == "/plans/v1/plans/91919/calendarNote"
    payload = client.post.call_args.kwargs["json"]
    assert payload["standardFormatDate"] == "Week 1, Monday"
    assert payload["attachments"] == []


@pytest.mark.asyncio
async def test_empty_test_plan_accepts_only_first_swim_as_bootstrap():
    """An empty plan with relative weeks may lack startDate/dayCount entirely.

    Permit exactly the preapproved pilot workout into the test plan. This does
    not assert the live provider will accept the command: a live readback is
    still mandatory.
    """
    empty = {
        "planId": 684206,
        "title": "[MCP TEST] Training Plan — Swim Bike Run",
        "startDate": None, "dayCount": None, "weekCount": 0,
        "workoutCount": None, "isPublic": False, "price": None,
    }
    inst = AsyncMock()
    inst.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=empty),
        APIResponse(success=True, data=[{
            "exerciseLibraryItemId": 14935065,
            "itemName": "[MCP TEST] Swim | Tecnica 1200 m - Builder",
        }]),
    ])
    inst.post = AsyncMock(return_value=APIResponse(success=True, data={}))
    p = _patch(inst)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=684206, library_id="3890637", item_id="14935065",
            workout_date="2027-06-21",
        )
    finally:
        p.stop()
    assert result["success"] is True
    assert result["readback_required"] is True
    assert inst.post.call_count == 1
    assert inst.post.call_args.args[0] == (
        "/plans/v1/plans/684206/commands/addworkoutfromlibraryitem"
    )
    assert inst.post.call_args.kwargs["json"]["workoutDateTime"] == "2027-06-21"


@pytest.mark.asyncio
async def test_empty_test_plan_rejects_other_workout_bootstraps():
    empty = {
        "planId": 684206,
        "title": "[MCP TEST] Training Plan — Swim Bike Run",
        "startDate": None, "dayCount": None, "weekCount": 0,
        "workoutCount": None, "isPublic": False, "price": None,
    }
    inst = AsyncMock()
    inst.get = AsyncMock(return_value=APIResponse(success=True, data=empty))
    inst.post = AsyncMock()
    p = _patch(inst)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=684206, library_id="3890637", item_id="14935073",
            workout_date="2027-06-21",
        )
    finally:
        p.stop()
    assert result["error_code"] == "VALIDATION_ERROR"
    inst.post.assert_not_called()


@pytest.mark.asyncio
async def test_bootstrap_disallowed_after_plan_has_workouts_without_date():
    empty = {
        "planId": 684206,
        "title": "[MCP TEST] Training Plan — Swim Bike Run",
        "startDate": None, "dayCount": None, "weekCount": 0,
        "workoutCount": 1, "isPublic": False, "price": None,
    }
    inst = AsyncMock()
    inst.get = AsyncMock(return_value=APIResponse(success=True, data=empty))
    inst.post = AsyncMock()
    p = _patch(inst)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=684206, library_id="3890637", item_id="14935065",
            workout_date="2027-06-21",
        )
    finally:
        p.stop()
    assert result["error_code"] == "VALIDATION_ERROR"
    inst.post.assert_not_called()



@pytest.mark.asyncio
async def test_test_plan_day_count_one_still_allows_full_first_week():
    """dayCount=1 after first workout is not the end of the named week."""
    plan = {
        **_TEST_PLAN, "weekCount": 1, "dayCount": 1, "workoutCount": 1,
    }
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=plan),
        APIResponse(success=True, data=[{
            "exerciseLibraryItemId": 14935073,
            "itemName": "[MCP TEST] Bike | 3x5' FTP controllato",
        }]),
        APIResponse(success=True, data=[{
            "workoutDay": "2027-06-21T00:00:00",
            "title": "[MCP TEST] Swim | Tecnica 1200 m - Builder",
        }]),
    ])
    client.post = AsyncMock(return_value=APIResponse(success=True, data={}))
    p = _patch(client)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=91919, library_id="3890637", item_id="14935073",
            workout_date="2027-06-22",
        )
    finally:
        p.stop()
    assert result["success"] is True
    assert client.post.call_args.kwargs["json"]["workoutDateTime"] == "2027-06-22"


@pytest.mark.asyncio
async def test_duplicate_library_workout_is_blocked_before_post():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data={
            **_TEST_PLAN, "weekCount": 1, "dayCount": 1, "workoutCount": 1,
        }),
        APIResponse(success=True, data=[{
            "exerciseLibraryItemId": 14935065,
            "itemName": "[MCP TEST] Swim 1200",
        }]),
        APIResponse(success=True, data=[{
            "workoutDay": "2027-06-21T00:00:00",
            "title": "[MCP TEST] Swim 1200",
        }]),
    ])
    client.post = AsyncMock()
    p = _patch(client)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=91919, library_id="3890637", item_id="14935065",
            workout_date="2027-06-21",
        )
    finally:
        p.stop()
    assert result["error_code"] == "ALREADY_EXISTS"
    client.post.assert_not_called()


@pytest.mark.asyncio
async def test_read_training_plan_notes_returns_relative_week_day():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data={
            **_TEST_PLAN, "weekCount": 1, "dayCount": 1,
        }),
        APIResponse(success=True, data=[{
            "calendarNoteId": 99515,
            "title": "[MCP TEST] Plan note",
            "noteDate": "2027-06-24T00:00:00",
            "description": "Test instructions",
        }]),
    ])
    p = _patch(client)
    try:
        result = await tp_get_training_plan_notes(plan_id=91919)
    finally:
        p.stop()
    assert result["count"] == 1
    assert result["notes"][0]["day"] == 4
    assert result["notes"][0]["week"] == 1
    assert result["notes"][0]["note_id"] == 99515
    assert "/calendarNote/2027-06-21/2027-06-29" in client.get.call_args.args[0]


@pytest.mark.asyncio
async def test_read_training_plan_notes_is_read_only():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_TEST_PLAN),
        APIResponse(success=True, data=[]),
    ])
    client.post = AsyncMock()
    p = _patch(client)
    try:
        result = await tp_get_training_plan_notes(plan_id=91919)
    finally:
        p.stop()
    assert result["count"] == 0
    client.post.assert_not_called()



@pytest.mark.asyncio
async def test_existing_workouts_reader_also_returns_native_plan_calendar_notes():
    """The established 88th-or-earlier MCP action also audits plan notes.

    This works even if the NEW tp_get_training_plan_notes tool is absent
    from the host's cached action list.
    """
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_TEST_PLAN),
        APIResponse(success=True, data=[{
            "workoutDay": "2027-06-21T00:00:00",
            "workoutTypeValueId": 1,
            "title": "[MCP TEST] Swim 1200 m",
            "totalTimePlanned": 0.5,
            "distancePlanned": 1200,
            "structure": {"primaryLengthMetric": "distance"},
        }]),
        APIResponse(success=True, data=_TEST_PLAN),
        APIResponse(success=True, data=[{
            "calendarNoteId": 99515,
            "title": "[MCP TEST] Instructions",
            "noteDate": "2027-06-24T00:00:00",
            "description": "Pilot plan instructions",
        }]),
    ])
    p = _patch(client)
    try:
        result = await tp_get_training_plan_workouts(91919)
    finally:
        p.stop()
    assert result["count"] == 1
    assert result["calendar_notes_status"] == "ok"
    assert result["calendar_notes_count"] == 1
    assert result["calendar_notes"][0]["title"] == "[MCP TEST] Instructions"
    assert result["calendar_notes"][0]["day"] == 4
    assert result["calendar_notes"][0]["week"] == 1
    assert "/calendarNote/2027-06-21/2027-06-29" in client.get.call_args.args[0]
    client.post.assert_not_called()


@pytest.mark.asyncio
async def test_workouts_reader_survives_a_notes_endpoint_failure():
    """Do not silently misreport zero notes when the notes endpoint fails."""
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_TEST_PLAN),
        APIResponse(success=True, data=[{
            "workoutDay": "2027-06-21T00:00:00",
            "workoutTypeValueId": 1,
            "title": "[MCP TEST] Swim 1200 m",
            "totalTimePlanned": 0.5,
        }]),
        APIResponse(success=True, data=_TEST_PLAN),
        APIResponse(success=False, message="Notes temporarily unavailable"),
    ])
    p = _patch(client)
    try:
        result = await tp_get_training_plan_workouts(91919)
    finally:
        p.stop()
    assert result["count"] == 1
    assert result["calendar_notes"] is None
    assert result["calendar_notes_status"] == "unavailable"
    assert result["calendar_notes_error"]["code"]


@pytest.mark.asyncio
async def test_plan_note_duplicate_is_detected_before_post():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_TEST_PLAN),
        APIResponse(success=True, data=[{
            "calendarNoteId": 99515,
            "title": "[MCP TEST] Instructions",
            "noteDate": "2027-06-24T00:00:00",
        }]),
    ])
    client.post = AsyncMock()
    p = _patch(client)
    try:
        result = await tp_add_training_plan_note(
            plan_id=91919,
            note_date="2027-06-24",
            title="[MCP TEST] Instructions",
            description="Do not duplicate the note.",
        )
    finally:
        p.stop()
    assert result["error_code"] == "ALREADY_EXISTS"
    client.post.assert_not_called()


@pytest.mark.asyncio
async def test_plan_note_aborts_on_unexpected_preflight_response():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_TEST_PLAN),
        APIResponse(success=True, data={"unexpected": "shape"}),
    ])
    client.post = AsyncMock()
    p = _patch(client)
    try:
        result = await tp_add_training_plan_note(
            plan_id=91919,
            note_date="2027-06-24",
            title="[MCP TEST] Instructions",
            description="Do not post without a reliable duplicate check.",
        )
    finally:
        p.stop()
    assert result["error_code"] == "API_ERROR"
    client.post.assert_not_called()



@pytest.mark.asyncio
async def test_plan_notes_reader_does_not_report_zero_on_unknown_payload():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_TEST_PLAN),
        APIResponse(success=True, data={"unexpected": "wrapper"}),
    ])
    p = _patch(client)
    try:
        result = await tp_get_training_plan_notes(plan_id=91919)
    finally:
        p.stop()
    assert result["isError"] is True
    assert result["error_code"] == "API_ERROR"
    assert "count" not in result


# Intermediate 24-week Training Plan Library staging — MOCK-ONLY regressions.
# Live writes remain forbidden until editable-install tests and provider
# readback confirm each stage in an unpriced [MCP TEST] private plan.
_INTERMEDIATE_PILOT_TITLE = "[MCP TEST] IRONMAN Intermediate 24W - Archive Pilot"
_INTERMEDIATE_FIRST_UID = "IMINT24W-W01-MON-OTHER-01"
_INTERMEDIATE_FIRST_ITEM = (
    "[MCP TEST] " + _INTERMEDIATE_FIRST_UID
    + " | SETTIMANA 1 | Calibrazione e riferimenti"
)


@pytest.mark.asyncio
async def test_create_intermediate_24w_private_pilot_exact_scope():
    inst = AsyncMock()
    inst.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=[]),
        APIResponse(success=True, data={
            "planId": 784206, "title": _INTERMEDIATE_PILOT_TITLE,
            "startDate": None, "dayCount": None, "weekCount": 0,
            "workoutCount": None, "isPublic": False, "price": None,
        }),
    ])
    inst.post = AsyncMock(return_value=APIResponse(
        success=True, data={"planId": 784206},
    ))
    p = _patch(inst)
    try:
        result = await tp_create_training_plan(
            title=_INTERMEDIATE_PILOT_TITLE,
            start_date="2027-01-04",
            week_count=24,
            description="PRIVATE archive pilot; no athlete sharing.",
        )
    finally:
        p.stop()
    assert result["success"] is True
    assert result["verified"] is True
    assert result["plan_id"] == 784206
    assert result["requested_weeks"] == 24
    assert result["provider_observed_weeks"] == 0
    assert result["calendar_bootstrap_pending"] is True
    payload = inst.post.call_args.kwargs["json"]
    assert payload["isPublic"] is False
    assert payload["weekCount"] == 24
    assert payload["dayCount"] == 168
    assert payload["startDate"] == "2027-01-04T00:00:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("title,start,weeks", [
    ("[MCP TEST] Something else", "2027-01-04", 24),
    ("[MCP TEST] IRONMAN Intermediate 24W - Archive Pilot", "2027-01-11", 24),
    ("[MCP TEST] IRONMAN Intermediate 24W - Archive Pilot", "2027-01-04", 4),
    ("[MCP TEST] IRONMAN Intermediate 24W - Archive Pilot", "2027-01-04", 25),
])
async def test_intermediate_pilot_rejects_other_plan_scopes(title, start, weeks):
    with patch("tp_mcp.tools.plans.TPClient") as client:
        result = await tp_create_training_plan(
            title=title, start_date=start, week_count=weeks,
        )
    assert result["isError"] is True
    client.assert_not_called()


def _intermediate_pilot_detail(
    start_date=None, workout_count=None, week_count=0, day_count=0,
):
    return {
        "planId": 784206,
        "title": _INTERMEDIATE_PILOT_TITLE,
        "startDate": (start_date + "T00:00:00") if start_date else None,
        "workoutCount": workout_count,
        "weekCount": week_count, "dayCount": day_count,
        "isPublic": False, "price": None,
    }


@pytest.mark.asyncio
async def test_intermediate_empty_pilot_accepts_only_first_monday_uid():
    inst = AsyncMock()
    inst.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_intermediate_pilot_detail()),
        APIResponse(success=True, data=[{
            "exerciseLibraryItemId": 2350001,
            "itemName": _INTERMEDIATE_FIRST_ITEM,
        }]),
    ])
    inst.post = AsyncMock(return_value=APIResponse(success=True, data={}))
    p = _patch(inst)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=784206, library_id="3890637", item_id="2350001",
            workout_date="2027-01-04",
        )
    finally:
        p.stop()
    assert result["success"] is True
    assert inst.post.await_count == 1
    assert inst.post.call_args.kwargs["json"]["workoutDateTime"] == "2027-01-04"


@pytest.mark.asyncio
@pytest.mark.parametrize("date,item_name", [
    ("2027-01-05", _INTERMEDIATE_FIRST_ITEM),
    ("2027-01-04", "[MCP TEST] IMINT24W-W01-TUE-SWIMMING-01 | Test T1500"),
    ("2027-01-04", "[MCP TEST] Old unrelated template"),
])
async def test_intermediate_empty_pilot_rejects_wrong_bootstrap(date, item_name):
    inst = AsyncMock()
    inst.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_intermediate_pilot_detail()),
        APIResponse(success=True, data=[{
            "exerciseLibraryItemId": 2350001,
            "itemName": item_name,
        }]),
    ])
    inst.post = AsyncMock()
    p = _patch(inst)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=784206, library_id="3890637", item_id="2350001",
            workout_date=date,
        )
    finally:
        p.stop()
    assert result["error_code"] == "PROTECTED_RESOURCE"
    inst.post.assert_not_called()


@pytest.mark.asyncio
async def test_intermediate_pilot_accepts_week4_beyond_reported_week_count():
    inst = AsyncMock()
    inst.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_intermediate_pilot_detail(
            start_date="2027-01-04", workout_count=13,
            week_count=1, day_count=7,
        )),
        APIResponse(success=True, data=[{
            "exerciseLibraryItemId": 2350002,
            "itemName": "[MCP TEST] IMINT24W-W04-FRI-CYCLING-02 | Bici facile",
        }]),
        APIResponse(success=True, data=[]),
    ])
    inst.post = AsyncMock(return_value=APIResponse(success=True, data={}))
    p = _patch(inst)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=784206, library_id="3890637", item_id="2350002",
            workout_date="2027-01-29",
        )
    finally:
        p.stop()
    assert result["success"] is True
    assert inst.get.call_args_list[-1].args[0] == (
        "/plans/v1/plans/784206/workouts/2027-01-29/2027-01-31"
    )
    assert inst.post.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("start,target", [
    ("2027-01-04", "2027-06-21"),  # day 169, outside 24 weeks
    ("2027-01-05", "2027-01-06"),  # shifted source week anchor
])
async def test_intermediate_pilot_refuses_outside_or_shifted(start, target):
    inst = AsyncMock()
    inst.get = AsyncMock(side_effect=[
        APIResponse(success=True, data=_intermediate_pilot_detail(
            start_date=start, workout_count=2, week_count=1, day_count=3,
        )),
        APIResponse(success=True, data=[{
            "exerciseLibraryItemId": 2350003,
            "itemName": "[MCP TEST] IMINT24W-W01-WED-RUNNING-01 | Corsa facile",
        }]),
    ])
    inst.post = AsyncMock()
    p = _patch(inst)
    try:
        result = await tp_add_training_plan_library_workout(
            plan_id=784206, library_id="3890637", item_id="2350003",
            workout_date=target,
        )
    finally:
        p.stop()
    assert result["error_code"] == "PROTECTED_RESOURCE"
    inst.post.assert_not_called()
