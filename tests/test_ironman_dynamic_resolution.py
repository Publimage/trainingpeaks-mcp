import asyncio
import pytest
from tp_mcp.ironman_dynamic_identity import TargetStop
from tp_mcp.ironman_dynamic_resolution import resolve_live_request

PLANS = [{"plan_id": 501, "title": "Foundation"}, {"plan_id": 902, "title": "Intermediate"}]
ATHLETES = [{"athlete_id": 11, "name": "Marco Rossi"}, {"athlete_id": 22, "name": "Marco Verdi"}]
LIBRARY = [{"id": 99, "name": "Swim", "owner_id": 2116886}, {"id": 31, "name": "Shared", "owner_id": 42}]
COUNTS = []


async def read_plans():
    COUNTS.append("plans")
    return {"plans": PLANS}


async def read_athletes():
    COUNTS.append("athletes")
    return {"athletes": ATHLETES}


async def read_libraries():
    COUNTS.append("libraries")
    return {"libraries": LIBRARY}


async def read_plan_workouts(plan_id):
    COUNTS.append("plan_workouts:" + str(plan_id))
    return {"plan_id": plan_id, "workouts": [{"workout_id": 51, "title": "Threshold", "day": 2}]}


async def read_plan_notes(plan_id):
    COUNTS.append("plan_notes:" + str(plan_id))
    return {"plan_id": plan_id, "notes": [{"note_id": 81, "title": "Coach instructions", "day": 1,
                                         "attachments": [{"id": 9, "file_name": "week.pdf"}]}]}


async def read_athlete_workouts(athlete_id, start, end):
    COUNTS.append("athlete_workouts:" + str(athlete_id))
    return {"workouts": [{"id": "77", "date": start, "title": "Easy bike", "type": "planned"}]}


def go(kind, query, **kwargs):
    return asyncio.run(resolve_live_request(
        kind, query, coach_id=kwargs.pop("coach_id", 2116886),
        read_plans=kwargs.pop("read_plans", read_plans),
        read_athletes=read_athletes, read_libraries=read_libraries,
        read_plan_workouts=kwargs.pop("read_plan_workouts", read_plan_workouts),
        read_plan_notes=kwargs.pop("read_plan_notes", read_plan_notes),
        read_athlete_workouts=read_athlete_workouts, **kwargs))


def setup_function():
    COUNTS.clear()


def test_dynamic_plan_without_old_manifest():
    result = go("training_plan", "902")
    assert result["target"]["container_id"] == 902
    assert result["publication_authorized"] is False
    assert COUNTS == ["plans"]


def test_plan_workout_only_uses_independently_resolved_plan():
    result = go("plan_workout", "Threshold", plan="Foundation", week=1, weekday=2)
    assert result["target"]["container_id"] == 501
    assert result["target"]["resource_id"] == 51
    assert COUNTS == ["plans", "plan_workouts:501"]


def test_same_plan_workout_cannot_be_loaded_by_wrong_plan_response():
    async def wrong(plan_id):
        return {"plan_id": 902, "workouts": [{"workout_id": 51, "title": "Threshold"}]}
    with pytest.raises(TargetStop, match="PLAN_READBACK_SCOPE_MISMATCH"):
        go("plan_workout", 51, plan=501, read_plan_workouts=wrong)


def test_nonexistent_plan_stops_before_plan_workout_provider_read():
    with pytest.raises(TargetStop, match="TARGET_NOT_FOUND"):
        go("plan_workout", "Threshold", plan="Unknown")
    assert COUNTS == ["plans"]


def test_athlete_workout_bound_to_coach_roster_and_date_window():
    result = go("athlete_workout", "Easy bike", athlete="Marco Verdi",
                start_date="2026-10-25", end_date="2026-10-26")
    assert result["target"]["athlete_id"] == 22
    assert result["target"]["resource_id"] == 77
    assert COUNTS == ["athletes", "athlete_workouts:22"]


@pytest.mark.parametrize("start,end", [(None, None), ("2026-10-25", "2026-10-01"),
                                             ("2026-01-01", "2026-10-25"),
                                             ("invalid", "2026-10-25")])
def test_athlete_workout_date_safety(start, end):
    with pytest.raises(TargetStop):
        go("athlete_workout", 77, athlete="Marco Rossi", start_date=start, end_date=end)
    assert COUNTS == ["athletes"]


def test_ambiguous_athlete_never_reads_calendar():
    with pytest.raises(TargetStop, match="TARGET_AMBIGUOUS"):
        go("athlete_workout", 77, athlete="Marco", start_date="2026-10-25", end_date="2026-10-25")
    assert COUNTS == ["athletes"]


def test_unowned_library_is_readable_but_never_grants_mutation():
    result = go("workout_library", "Shared")
    assert result["is_coach_owned"] is False
    assert result["publication_authorized"] is False


def test_new_plan_has_no_fake_provider_id():
    result = go("new_training_plan", "Brand new 2030 plan")
    assert result["provider_resource_id"] is None
    with pytest.raises(TargetStop, match="CREATE_NAME_CONFLICT"):
        go("new_training_plan", "Foundation")


def test_wrong_account_cannot_read_anything():
    with pytest.raises(TargetStop, match="ACCOUNT_MISMATCH"):
        go("training_plan", 501, coach_id=1234)
    assert COUNTS == []


def test_new_plan_note_and_pdf_destination_are_not_attributed_to_an_athlete():
    found = go("plan_note", "Coach instructions", plan="Foundation", week=1, weekday=1)
    assert found["kind"] == "plan_note"
    assert found["target"]["container_id"] == 501
    assert found["target"]["resource_id"] == 81
    assert found["note"]["attachments"][0]["file_name"] == "week.pdf"
    assert COUNTS == ["plans", "plan_notes:501"]


def test_plan_note_denies_wrong_provider_plan_readback():
    async def wrong(plan_id):
        return {"plan_id": 902, "notes": []}
    with pytest.raises(TargetStop, match="PLAN_READBACK_SCOPE_MISMATCH"):
        go("plan_note", "Coach instructions", plan="Foundation", read_plan_notes=wrong)
