"""Offline host adapter tests; all TP endpoints are synthetic reader fakes."""
import asyncio
import contextvars
import importlib.util
from pathlib import Path
import sys
import types

import pytest


@pytest.fixture
def host(monkeypatch):
    path = Path(__file__).parents[1] / "src/tp_mcp/ironman_dynamic_targets.py"
    athlete_override = contextvars.ContextVar("athlete_override", default=None)
    events = []
    state = {"coach_id": 2116886}

    class FakeTPClient:
        async def __aenter__(self):
            events.append(("session", athlete_override.get()))
            return self

        async def __aexit__(self, *args):
            return False

        async def _get_user_data(self):
            return {"personId": state["coach_id"]}

    async def plans():
        events.append(("plans", athlete_override.get()))
        return {"plans": [{"plan_id": 456, "title": "New plan from another chat"}]}

    async def athletes():
        events.append(("roster", athlete_override.get()))
        return {"athletes": [{"athlete_id": 99, "name": "Athlete A"}]}

    async def libraries():
        return {"libraries": []}

    async def plan_workouts(plan_id):
        events.append(("plan_workouts", athlete_override.get()))
        return {"plan_id": plan_id,
                "workouts": [{"workout_id": 700, "title": "Swim technique", "day": 1}]}

    async def plan_notes(plan_id):
        events.append(("plan_notes", athlete_override.get()))
        return {"plan_id": plan_id,
                "notes": [{"note_id": 301, "title": "PDF instructions", "day": 1}]}

    async def athlete_workouts(start, end, workout_filter):
        events.append(("athlete_workouts", athlete_override.get()))
        assert workout_filter == "all"
        return {"workouts": [{"id": "800", "title": "Easy run", "date": start}]}

    stubs = {
        "tp_mcp.client": {"TPClient": FakeTPClient},
        "tp_mcp.client.context": {"athlete_override": athlete_override},
        "tp_mcp.tools.library": {"tp_get_libraries": libraries},
        "tp_mcp.tools.plans": {"tp_get_training_plan_workouts": plan_workouts,
                               "tp_get_training_plan_notes": plan_notes,
                               "tp_list_training_plans": plans},
        "tp_mcp.tools.profile": {"tp_list_athletes": athletes},
        "tp_mcp.tools.workouts": {"tp_get_workouts": athlete_workouts},
    }
    for name, attributes in stubs.items():
        module = types.ModuleType(name)
        for key, value in attributes.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("_synthetic_ironman_dynamic_host", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, events, state, athlete_override


def test_host_generic_any_new_plan_no_hardcoded_workout_id(host):
    tool, events, state, context = host
    result = asyncio.run(tool.tp_ironman_resolve_target("training_plan", "another chat"))
    assert result["target"]["container_id"] == 456
    assert result["publication_authorized"] is False
    assert ("plans", None) in events
    assert context.get() is None


def test_host_guard_stops_wrong_coach_before_plan_list(host):
    tool, events, state, context = host
    state["coach_id"] = 999999
    result = asyncio.run(tool.tp_ironman_resolve_target("training_plan", "456"))
    assert result["isError"] is True
    assert result["error_code"] == "ACCOUNT_MISMATCH"
    assert not any(kind == "plans" for kind, _ in events)


def test_host_calendar_reads_only_selected_roster_athlete(host):
    tool, events, state, context = host
    result = asyncio.run(tool.tp_ironman_resolve_target(
        "athlete_workout", "Easy run", athlete_selector="Athlete A",
        start_date="2026-10-20", end_date="2026-10-20"))
    assert result["target"]["athlete_id"] == 99
    assert result["target"]["resource_id"] == 800
    assert ("athlete_workouts", "99") in events
    assert ("roster", None) in events
    assert context.get() is None


def test_host_does_not_inherit_session_selected_athlete(host):
    tool, events, state, context = host
    token = context.set("777777")
    try:
        result = asyncio.run(tool.tp_ironman_resolve_target("training_plan", "456"))
        assert result["target"]["container_id"] == 456
        assert ("plans", None) in events
        assert context.get() == "777777"  # restoration, no leak to next handler
    finally:
        context.reset(token)


def test_host_resolves_new_pdf_note_destination_without_calendar_mixup(host):
    tool, events, state, context = host
    result = asyncio.run(tool.tp_ironman_resolve_target(
        "plan_note", "PDF instructions", plan_selector="new plan", week=1, weekday=1))
    assert result["target"]["container_id"] == 456
    assert result["target"]["resource_id"] == 301
    assert ("plan_notes", None) in events
    assert not any(k == "roster" for k, v in events)
