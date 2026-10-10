"""Offline guards for the native NoteTemplate publisher; no TrainingPeaks credentials."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "native_note_publisher_test_target", ROOT / "scripts" / "publish_native_notes_library.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def approved_notes():
    return [
        {
            "canonical_uid": f"NOTE-{i:02d}",
            "title": f"Native note {i:02d}",
            "description": f"Body for note {i}",
            "qa_status": "PASS",
            "approval_status": "APPROVED",
            "language": "it-IT",
        }
        for i in range(35)
    ]


def manifest(notes=None):
    return {
        "schema": "IRONMAN_NOTE_NATIVE_LIBRARY_QUEUE_V1",
        "kind": "SNAPSHOT_NOT_SOURCE_OF_TRUTH",
        "source_sheet": "IRONMAN — WORKOUT ARCHIVE MASTER / NOTES_LIBRARY",
        "provider_plan_id": 684602,
        "provider_library_id": module.PRODUCTION_LIBRARY_ID,
        "desired_native_type": "NoteTemplate",
        "count": 35,
        "notes": notes if notes is not None else approved_notes(),
    }


def native_item(note):
    return {
        "exerciseLibraryId": module.PRODUCTION_LIBRARY_ID,
        "exerciseLibraryItemId": 10000 + int(note["canonical_uid"][-2:]),
        "exerciseLibraryItemType": "NoteTemplate",
        "workoutTypeId": 0,
        "itemName": note["title"],
        "description": note["description"],
        "structure": None,
        "totalTimePlanned": None,
    }


def test_approved_manifest_35_passes():
    assert len(module.validate_export(manifest())) == 35


@pytest.mark.parametrize("field,value", [
    ("schema", "unexpected"),
    ("count", 34),
    ("provider_plan_id", 123),
    ("source_sheet", "not canonical"),
    ("desired_native_type", "WorkoutTemplate"),
])
def test_manifest_identity_fail_closed(field, value):
    data = manifest()
    data[field] = value
    with pytest.raises(RuntimeError, match="STOP"):
        module.validate_export(data)


def test_empty_target_needs_all_35():
    assert module.validate_target_items([], approved_notes()) == 0


def test_exact_partial_and_complete_native_target_pass():
    notes = approved_notes()
    assert module.validate_target_items([native_item(x) for x in notes[:3]], notes) == 3
    assert module.validate_target_items([native_item(x) for x in notes], notes) == 35


def test_foreign_item_blocks_batch():
    with pytest.raises(RuntimeError, match="Unexpected unrelated"):
        module.validate_target_items([native_item({
            "canonical_uid": "NOTE-98", "title": "Unrelated",
            "description": "Never publish this",
        })], approved_notes())


def test_workout_template_cannot_impersonate_note():
    item = native_item(approved_notes()[0])
    item["exerciseLibraryItemType"] = "WorkoutTemplate"
    with pytest.raises(RuntimeError, match="NOT the approved"):
        module.validate_target_items([item], approved_notes())


def test_duplicate_name_fails_closed():
    item = native_item(approved_notes()[0])
    with pytest.raises(RuntimeError, match="Duplicate"):
        module.validate_target_items([item, dict(item, exerciseLibraryItemId=99999)], approved_notes())


def test_modified_body_fails_closed():
    item = native_item(approved_notes()[0])
    item["description"] = "CHANGED"
    with pytest.raises(RuntimeError, match="NOT the approved"):
        module.validate_target_items([item], approved_notes())


def test_only_two_explicit_library_ids_permitted():
    with pytest.raises(RuntimeError, match="Unknown destination"):
        module.note_template_payload(234, "title", "body")


def test_generated_payload_requests_real_native_type():
    payload = module.note_template_payload(module.PRODUCTION_LIBRARY_ID, "x", "y")
    assert payload["exerciseLibraryItemType"] == "NoteTemplate"
    assert payload["workoutTypeId"] == 0
    assert "totalTimePlanned" not in payload
