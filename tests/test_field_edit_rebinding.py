"""Fail-closed tests for rebinding stale workout IDs to actual provider IDs.

Only synthesized workout/note dictionaries; no credentials or provider writes.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from field_edits import ScopeError  # noqa: E402
from tp_field_edit_live import bind_notes, bind_workouts  # noqa: E402


def _workout_pair():
    monday = date(2026, 10, 5)
    manifests = []
    native = []
    for k in range(229):
        day = k + 1
        date_str = (monday + timedelta(days=k)).isoformat()
        sport = ["Swim", "Bike", "Run"][k % 3]
        sport_type = {"Swim": 1, "Bike": 2, "Run": 3}[sport]
        title = f"Structured endurance {k}"
        description = f"RPE 3 easy block {k}"
        old_id = 500_000 + k
        new_id = 600_000 + k
        manifests.append({
            "workout_id": old_id, "canonical_uid": f"uid-{k}",
            "week": k // 7 + 1, "day": day, "sport": sport,
            "title_after": title, "description_length": len(description),
        })
        native.append({
            "workoutId": new_id, "workoutDay": date_str + "T00:00:00",
            "workoutTypeValueId": sport_type, "title": title,
            "description": description,
        })
    return manifests, native


def _notes_pair():
    manifests, native = [], []
    for k in range(35):
        d = (date(2026, 10, 5) + timedelta(days=k)).isoformat()
        manifests.append({
            "uid": f"note-{k}", "note_id": 700_000 + k, "title_after": f"Note {k}",
            "date": d, "description": f"Description {k}", "week": k // 7 + 1,
        })
        native.append({
            "id": 700_000 + k, "noteDate": d, "title": f"Note {k}",
            "description": f"Description {k}",
        })
    return manifests, native


def test_old_ids_replaced_with_current_provider_ids():
    source, current = _workout_pair()
    records = bind_workouts(source, current)
    assert len(records) == 229
    assert records[0].provider_id == 600_000
    assert records[0].provider_id != source[0]["workout_id"]


def test_ambiguous_native_workout_fails_before_edit():
    source, current = _workout_pair()
    current[1] = dict(current[0], workoutId=650_000)
    with pytest.raises(ScopeError):
        bind_workouts(source, current)


def test_native_title_change_blocks_reconciliation():
    source, current = _workout_pair()
    current[0]["title"] = "Unexpected new title"
    with pytest.raises(ScopeError):
        bind_workouts(source, current)


def test_changed_workout_description_blocks_reconciliation():
    source, current = _workout_pair()
    current[0]["description"] += " edited"
    with pytest.raises(ScopeError):
        bind_workouts(source, current)


def test_exact_native_notes_bind_without_other_workout_fallback():
    source, current = _notes_pair()
    records = bind_notes(source, current)
    assert len(records) == 35
    assert records[-1].provider_id == 700_034


def test_changed_native_note_body_blocks_reconciliation():
    source, current = _notes_pair()
    current[0]["description"] = "Unexpected body"
    with pytest.raises(ScopeError):
        bind_notes(source, current)
