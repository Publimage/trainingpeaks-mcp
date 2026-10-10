"""Offline safety/regression tests for native TrainingPeaks NoteTemplate publishing.

The API is ALWAYS mocked: these tests never contact a real TP account.
"""
from __future__ import annotations

import copy
import json

import pytest

from tp_mcp.server import TOOLS, _TOOL_HANDLERS
from tp_mcp.tools import native_note_library as mod


def _manifest() -> dict:
    return json.loads(mod.EXPORT_PATH.read_text(encoding="utf-8"))


def _item(library_id: int, title: str, body: str, item_type: str = "NoteTemplate") -> dict:
    return {
        **mod._native_payload(library_id, title, body),
        "exerciseLibraryItemId": 9000,
        "exerciseLibraryItemType": item_type,
        "structure": None,
        "totalTimePlanned": None,
    }


class FakeResponse:
    def __init__(self, data, is_error=False):
        self.data = data
        self.is_error = is_error


class FakeTPClient:
    def __init__(self):
        self.next_id = 9100
        self.items = {mod.LAB_ID: [], mod.TARGET_ID: []}
        self.post_calls = []
        self.convert_to_classic = False
        self.suppress_post = False
        self.athlete_id = mod.COACH_ID

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def ensure_athlete_id(self):
        return self.athlete_id

    async def get(self, path):
        if path == "/exerciselibrary/v2/libraries":
            return FakeResponse([
                {"exerciseLibraryId": mod.LAB_ID, "libraryName": mod.LAB_TITLE,
                 "ownerId": mod.COACH_ID},
                {"exerciseLibraryId": mod.TARGET_ID, "libraryName": mod.TARGET_TITLE,
                 "ownerId": mod.COACH_ID},
            ])
        for library_id, items in self.items.items():
            if path == f"/exerciselibrary/v2/libraries/{library_id}/items":
                return FakeResponse(copy.deepcopy(items))
        raise AssertionError(f"Unexpected fake GET path: {path}")

    async def post(self, path, json):
        self.post_calls.append((path, copy.deepcopy(json)))
        if self.suppress_post:
            return FakeResponse({"exerciseLibraryItemId": self.next_id})
        library_id = json["exerciseLibraryId"]
        assert path == f"/exerciselibrary/v1/libraries/{library_id}/items"
        self.next_id += 1
        item = {**json, "exerciseLibraryItemId": self.next_id,
                "exerciseLibraryItemType": "WorkoutTemplate"
                if self.convert_to_classic else "NoteTemplate",
                "structure": None, "totalTimePlanned": None}
        self.items[library_id].append(item)
        return FakeResponse({"exerciseLibraryItemId": self.next_id})


def _wire(monkeypatch, fake):
    monkeypatch.setattr(mod, "TPClient", lambda: fake)

    async def verified_plan(_notes):
        assert len(_notes) == 35

    monkeypatch.setattr(mod, "_assert_live_plan", verified_plan)


def test_canonical_manifest_has_35_unique_approved_notes():
    notes = mod._validate_manifest(_manifest())
    assert len(notes) == 35
    assert len({x["canonical_uid"] for x in notes}) == 35
    assert len({x["title"] for x in notes}) == 35
    assert any(n["title"] == "README FIRST | INIZIA DA QUI" for n in notes)


def test_reject_duplicate_title_before_any_api_call():
    manifest = _manifest()
    manifest["notes"][1]["title"] = manifest["notes"][0]["title"]
    with pytest.raises(mod.NativeNoteStop, match="Duplicate title"):
        mod._validate_manifest(manifest)


def test_template_type_must_be_native_and_exact():
    item = _item(mod.TARGET_ID, "A", "B")
    assert mod._is_exact_native(item, "A", "B")
    assert not mod._is_exact_native({**item, "exerciseLibraryItemType": "WorkoutTemplate"}, "A", "B")
    assert not mod._is_exact_native({**item, "description": "Changed"}, "A", "B")
    assert not mod._is_exact_native({**item, "totalTimePlanned": 1}, "A", "B")


def test_existing_unrelated_item_blocks_target_batch():
    notes = mod._validate_manifest(_manifest())
    with pytest.raises(mod.NativeNoteStop, match="Unrelated"):
        mod._validate_target([_item(mod.TARGET_ID, "Not canonical", "Hello")], notes)


def test_registration_is_coach_scoped_and_non_idempotent():
    item = next(x for x in TOOLS if x.name == "tp_sync_intermediate_native_notes")
    assert "athlete" not in item.input_schema["properties"]
    assert item.annotations.read_only_hint is False
    assert item.annotations.idempotent_hint is False
    assert item.annotations.destructive_hint is False
    assert "tp_sync_intermediate_native_notes" in _TOOL_HANDLERS


@pytest.mark.asyncio
async def test_preview_does_not_post(monkeypatch):
    fake = FakeTPClient()
    _wire(monkeypatch, fake)
    result = await mod.tp_sync_intermediate_native_notes()
    assert result["stage"] == "PREVIEW"
    assert result["remaining"] == 35
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_no_lab_ack_no_writes(monkeypatch):
    fake = FakeTPClient()
    _wire(monkeypatch, fake)
    result = await mod.tp_sync_intermediate_native_notes(mode="probe", ack_library_id=1)
    assert result["isError"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_lab_canary_then_35_native_templates(monkeypatch):
    fake = FakeTPClient()
    _wire(monkeypatch, fake)
    preview = await mod.tp_sync_intermediate_native_notes()
    assert preview["remaining"] == 35
    probe = await mod.tp_sync_intermediate_native_notes(mode="probe", ack_library_id=mod.LAB_ID)
    assert probe["stage"] == "LAB_NATIVE_PROBE_PASS"
    assert len(fake.items[mod.LAB_ID]) == 1

    result = await mod.tp_sync_intermediate_native_notes(
        mode="publish", ack_library_id=mod.TARGET_ID,
    )
    assert result["success"] is True
    assert result["stage"] == "PUBLISHED"
    assert result["native_notes"] == 35
    assert len(fake.items[mod.TARGET_ID]) == 35
    assert all(it["exerciseLibraryItemType"] == "NoteTemplate"
               for it in fake.items[mod.TARGET_ID])
    assert len(fake.post_calls) == 36

    # A complete repeat may only read and verify; zero duplicate POSTs.
    rerun = await mod.tp_sync_intermediate_native_notes(
        mode="publish", ack_library_id=mod.TARGET_ID,
    )
    assert rerun["native_notes"] == 35
    assert len(fake.post_calls) == 36


@pytest.mark.asyncio
async def test_provider_silently_creates_classic_type_stop_no_retry(monkeypatch):
    fake = FakeTPClient()
    fake.convert_to_classic = True
    _wire(monkeypatch, fake)
    result = await mod.tp_sync_intermediate_native_notes(
        mode="probe", ack_library_id=mod.LAB_ID,
    )
    assert result["isError"] is True
    assert result["never_retry_ambiguous_post"] is True
    assert len(fake.post_calls) == 1
    assert fake.items[mod.LAB_ID][0]["exerciseLibraryItemType"] == "WorkoutTemplate"


@pytest.mark.asyncio
async def test_unverified_post_stop_no_retry(monkeypatch):
    fake = FakeTPClient()
    fake.suppress_post = True
    _wire(monkeypatch, fake)
    result = await mod.tp_sync_intermediate_native_notes(
        mode="probe", ack_library_id=mod.LAB_ID,
    )
    assert result["isError"] is True
    assert len(fake.post_calls) == 1
    assert fake.items[mod.LAB_ID] == []


@pytest.mark.asyncio
async def test_wrong_connected_coach_prevents_all_post(monkeypatch):
    fake = FakeTPClient()
    fake.athlete_id = 42
    _wire(monkeypatch, fake)
    result = await mod.tp_sync_intermediate_native_notes(
        mode="probe", ack_library_id=mod.LAB_ID,
    )
    assert result["isError"]
    assert fake.post_calls == []
