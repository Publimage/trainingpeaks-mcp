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
async def test_apply_copies_workouts_skips_period_markers():
    """Synthetic apply: each plan workout is recreated at start_date + relative
    day (structure preserved as a JSON string); type-100 period markers skipped."""
    post = APIResponse(success=True, data={"workoutId": 999})
    inst = _client_with(_get_router, post=post)
    p = _patch(inst)
    try:
        r = await tp_apply_training_plan(163992, "2027-09-01")
    finally:
        p.stop()
    assert r["success"] is True and r["method"] == "synthetic"
    assert r["created"] == 2          # run + day-off
    assert r["skipped_periods"] == 1  # the type-100 annotation
    assert r["failed"] == 0
    creates = [c.kwargs["json"] for c in inst.post.call_args_list
               if "/fitness/v6/" in c.args[0]]
    run_post = next(b for b in creates if b["workoutTypeValueId"] == 3)
    assert run_post["workoutDay"] == "2027-09-02T00:00:00"  # start_date + rel day 1
    assert run_post["workoutTypeFamilyId"] == 3
    assert isinstance(run_post["structure"], str) and "primaryLengthMetric" in run_post["structure"]


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
