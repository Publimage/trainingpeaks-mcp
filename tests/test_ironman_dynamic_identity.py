"""Offline tests: dynamic target binding never needs a registered plan ID."""
import pytest
from tp_mcp.ironman_dynamic_identity import (
    TargetStop, require_new_name_absent, resolve_plan_workout, select_live_item,
)

PLANS = [
    {"plan_id": 501, "title": "Winter Foundation", "is_public": False},
    {"plan_id": 777, "title": "70.3 Beginner", "is_public": True},
    {"plan_id": 902, "title": "Winter Durability", "is_public": False},
]


def test_any_new_provider_plan_is_selectable_without_a_code_registry():
    for plan in PLANS:
        binding = select_live_item(PLANS, plan["plan_id"], id_field="plan_id",
                                   title_field="title", scope="training_plan")
        assert binding["record"]["plan_id"] == plan["plan_id"]
        assert binding["match"] == "exact_id"
        assert binding["verified_from"] == "trainingpeaks_live_inventory"


def test_unknown_new_plan_from_later_chat_also_works():
    rows = PLANS + [{"plan_id": 987654321, "title": "New private 2027 plan"}]
    assert select_live_item(rows, "New private 2027 plan", id_field="plan_id",
                            title_field="title", scope="training_plan")["record"]["plan_id"] == 987654321


def test_unique_fragment_is_convenient_but_ambiguous_fragment_is_blocked():
    got = select_live_item(PLANS, "beginner", id_field="plan_id",
                           title_field="title", scope="training_plan")
    assert got["record"]["plan_id"] == 777
    assert got["match"] == "unique_name_fragment"
    with pytest.raises(TargetStop, match="TARGET_AMBIGUOUS") as e:
        select_live_item(PLANS, "winter", id_field="plan_id", title_field="title", scope="training_plan")
    assert {x["id"] for x in e.value.candidates} == {501, 902}


@pytest.mark.parametrize("query", [None, True, "", "  ", 0, -11, "999999999999999999999999999"])
def test_bad_queries_are_rejected(query):
    with pytest.raises(TargetStop):
        select_live_item(PLANS, query, id_field="plan_id", title_field="title", scope="training_plan")


def test_wrong_id_does_not_fallback_to_old_manifest_or_title():
    with pytest.raises(TargetStop, match="TARGET_NOT_FOUND"):
        select_live_item(PLANS, "689369", id_field="plan_id", title_field="title", scope="training_plan")


def test_duplicate_provider_identity_fails_closed():
    with pytest.raises(TargetStop, match="PROVIDER_DUPLICATE_IDS"):
        select_live_item(PLANS + [PLANS[0]], "winter foundation", id_field="plan_id", title_field="title", scope="training_plan")


def test_athletes_never_chosen_by_last_used_profile():
    roster = [{"athlete_id": 11, "name": "Marco Rossi"}, {"athlete_id": 22, "name": "Marco Verdi"}]
    with pytest.raises(TargetStop, match="TARGET_AMBIGUOUS"):
        select_live_item(roster, "Marco", id_field="athlete_id", title_field="name", scope="athlete")
    assert select_live_item(roster, "22", id_field="athlete_id", title_field="name", scope="athlete")["record"]["athlete_id"] == 22


def test_plan_workout_requires_bound_plan_and_disambiguated_relative_slot():
    workouts = [{"workout_id": 31, "title": "Easy run", "day": 2},
                {"workout_id": 32, "title": "Easy run", "day": 9}]
    with pytest.raises(TargetStop, match="TARGET_AMBIGUOUS"):
        resolve_plan_workout(workouts, "Easy run", plan_id=500)
    got = resolve_plan_workout(workouts, "Easy run", plan_id=500, week=2, weekday=2)
    assert got["target"] == {"provider": "trainingpeaks", "container_kind": "training_plan", "container_id": 500, "resource_id": 32}
    with pytest.raises(TargetStop, match="RELATIVE_SLOT_INCOMPLETE"):
        resolve_plan_workout(workouts, "Easy run", plan_id=500, week=2)
    with pytest.raises(TargetStop, match="PLAN_TARGET_REQUIRED"):
        resolve_plan_workout(workouts, "Easy run", plan_id=0)


def test_create_preflight_handles_absent_without_fake_id_and_prevents_duplicate():
    candidate = require_new_name_absent(PLANS, " Brand new plan ", id_field="plan_id",
                                        title_field="title", scope="training_plan")
    assert candidate["provider_resource_id"] is None
    assert candidate["title"] == "Brand new plan"
    assert candidate["absence_checked"] is True
    with pytest.raises(TargetStop, match="CREATE_NAME_CONFLICT"):
        require_new_name_absent(PLANS, "WINTER FOUNDATION", id_field="plan_id",
                                title_field="title", scope="training_plan")



def test_create_preflight_rejects_duplicate_provider_ids_and_oversized_inventory():
    rows = PLANS + [{"plan_id": 501, "title": "Unrelated repeated identity"}]
    with pytest.raises(TargetStop, match="PROVIDER_DUPLICATE_IDS"):
        require_new_name_absent(rows, "Another brand new plan",
                                id_field="plan_id", title_field="title",
                                scope="training_plan")
    oversized = [{"plan_id": i + 1, "title": f"Plan {i}"}
                 for i in range(10001)]
    with pytest.raises(TargetStop, match="PROVIDER_INVENTORY_INVALID"):
        require_new_name_absent(oversized, "Brand new plan",
                                id_field="plan_id", title_field="title",
                                scope="training_plan")
