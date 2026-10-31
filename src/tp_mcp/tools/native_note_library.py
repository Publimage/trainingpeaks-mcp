"""Guarded native NoteTemplate publication for the private Intermediate 24W product.

The authoritative text lives in Google Drive NOTES_LIBRARY. The versioned
JSON manifest is only an approved export, cross-checked against live plan Notes
before writes. No athlete-calendar methods, deletes, or automatic retries.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tp_mcp.client import TPClient
from tp_mcp.tools.plans import tp_get_training_plan, tp_get_training_plan_notes

COACH_ID = 2116886
PLAN_ID = 684602
PLAN_TITLE = "[MCP TEST] IRONMAN Intermediate Assembly 24W"
LAB_ID = 3890637
LAB_TITLE = "[MCP TEST] Integration Lab"
TARGET_ID = 3892900
TARGET_TITLE = "IRONMAN MASTER | Note"
CANARY_TITLE = "[MCP TEST] NoteTemplate library API type-canary"
CANARY_BODY = "Disposable native NoteTemplate type canary; no athlete/plan calendar writes."
EXPORT_PATH = (
    Path(__file__).resolve().parents[3]
    / "data" / "intermediate_native_note_library_queue.json"
)


class NativeNoteStop(Exception):
    """Fail closed: never retry a write with an ambiguous provider result."""


def _stop(message: str) -> None:
    raise NativeNoteStop(message)


def _validate_manifest(data: dict[str, Any]) -> list[dict[str, Any]]:
    notes = data.get("notes")
    if (
        data.get("schema") != "IRONMAN_NOTE_NATIVE_LIBRARY_QUEUE_V1"
        or data.get("kind") != "SNAPSHOT_NOT_SOURCE_OF_TRUTH"
        or data.get("provider_plan_id") != PLAN_ID
        or data.get("provider_library_id") != TARGET_ID
        or data.get("desired_native_type") != "NoteTemplate"
        or data.get("source_sheet") != "IRONMAN — WORKOUT ARCHIVE MASTER / NOTES_LIBRARY"
        or data.get("count") != 35
        or not isinstance(notes, list)
        or len(notes) != 35
    ):
        _stop("Unapproved or incomplete 35-note manifest.")
    seen_title: set[str] = set()
    seen_uid: set[str] = set()
    for note in notes:
        if not isinstance(note, dict):
            _stop("Malformed note manifest.")
        title, body, uid = (note.get(k) for k in ("title", "description", "canonical_uid"))
        if not all(isinstance(v, str) and v.strip() for v in (title, body, uid)):
            _stop("Missing canonical title, body or UID.")
        if title in seen_title or uid in seen_uid:
            _stop("Duplicate title or UID in canonical notes.")
        if (note.get("qa_status") != "PASS"
            or note.get("approval_status") != "APPROVED"
            or note.get("language") != "it-IT"):
            _stop("Unapproved canonical note.")
        seen_title.add(title)
        seen_uid.add(uid)
    return notes


def _native_payload(library_id: int, title: str, body: str) -> dict[str, Any]:
    if library_id not in (LAB_ID, TARGET_ID):
        _stop("Unsafe destination library.")
    return {
        "exerciseLibraryId": library_id,
        "exerciseLibraryItemType": "NoteTemplate",
        "itemName": title,
        "workoutTypeId": 0,
        "description": body,
    }


def _is_exact_native(item: dict[str, Any], title: str, body: str) -> bool:
    return (
        item.get("exerciseLibraryItemType") == "NoteTemplate"
        and item.get("workoutTypeId") == 0
        and item.get("itemName") == title
        and item.get("description") == body
        and item.get("structure") is None
        and item.get("totalTimePlanned") is None
    )


async def _read_items(client: TPClient, library_id: int) -> list[dict[str, Any]]:
    resp = await client.get(f"/exerciselibrary/v2/libraries/{library_id}/items")
    if resp.is_error or not isinstance(resp.data, list):
        _stop(f"Library {library_id} GET unavailable; no write.")
    items = resp.data
    if any(
        not isinstance(x, dict) or x.get("exerciseLibraryId") != library_id
        for x in items
    ):
        _stop("Library GET returned mismatched owner or item data.")
    return items


def _find_exact(items: list[dict[str, Any]], title: str, body: str) -> int | None:
    matches = [item for item in items if item.get("itemName") == title]
    if len(matches) > 1:
        _stop(f"Duplicate title in provider library: {title}")
    if not matches:
        return None
    if not _is_exact_native(matches[0], title, body):
        _stop(f"Existing item is not approved native NoteTemplate: {title}")
    item_id = matches[0].get("exerciseLibraryItemId")
    if type(item_id) is not int or item_id <= 0:
        _stop("Native NoteTemplate has no verified item ID.")
    return item_id


def _validate_target(items: list[dict[str, Any]], notes: list[dict[str, Any]]) -> int:
    if len(items) > len(notes):
        _stop("Target library exceeds approved 35-note set.")
    approved = {n["title"]: n["description"] for n in notes}
    if len({x.get("itemName") for x in items}) != len(items):
        _stop("Duplicate title in target library.")
    for item in items:
        title = item.get("itemName")
        if title not in approved:
            _stop("Unrelated item present in target Notes library.")
        _find_exact(items, title, approved[title])
    return len(items)


async def _assert_owner_and_libraries(client: TPClient) -> None:
    # The owning coach's personId is NOT necessarily the coach's own
    # athleteId. ensure_athlete_id() resolves the self-athlete roster entry
    # (856352 on this account), whereas library.ownerId is personId (2116886).
    # Check the authenticated user identity directly; never relax ownership.
    user_data = await client._get_user_data()
    if not isinstance(user_data, dict) or user_data.get("personId") != COACH_ID:
        _stop("TrainingPeaks coach account mismatch. No write.")
    resp = await client.get("/exerciselibrary/v2/libraries")
    if resp.is_error or not isinstance(resp.data, list):
        _stop("Provider library ownership unavailable.")
    by_id = {row.get("exerciseLibraryId"): row for row in resp.data
             if isinstance(row, dict)}
    for lib_id, title in ((LAB_ID, LAB_TITLE), (TARGET_ID, TARGET_TITLE)):
        lib = by_id.get(lib_id)
        if not lib or lib.get("libraryName") != title or lib.get("ownerId") != COACH_ID:
            _stop(f"Unverified owner/name for library {lib_id}.")


async def _assert_live_plan(notes: list[dict[str, Any]]) -> None:
    plan = await tp_get_training_plan(plan_id=PLAN_ID)
    if (
        plan.get("isError")
        or plan.get("title") != PLAN_TITLE
        or plan.get("workouts") != 259
        or plan.get("weeks") != 24
    ):
        _stop("Private Intermediate plan count/identity changed.")
    result = await tp_get_training_plan_notes(plan_id=PLAN_ID)
    actual = result.get("notes") if not result.get("isError") else None
    if not isinstance(actual, list) or len(actual) != 35:
        _stop("Live plan must contain exactly 35 Notes.")
    expected = {(x["title"], x["description"]) for x in notes}
    observed = {(x.get("title"), x.get("description")) for x in actual}
    if expected != observed or len(observed) != 35:
        _stop("Canonical export and live plan Notes differ. No publication.")


async def _create_verified(
    client: TPClient, library_id: int, title: str, body: str,
) -> int:
    before = await _read_items(client, library_id)
    found = _find_exact(before, title, body)
    if found is not None:
        return found
    result = await client.post(
        f"/exerciselibrary/v1/libraries/{library_id}/items",
        json=_native_payload(library_id, title, body),
    )
    if result.is_error:
        _stop("Provider rejected native NoteTemplate; do not use WorkoutTemplate.")
    # A missing readback is ambiguous: STOP, never retry a POST.
    after = await _read_items(client, library_id)
    item_id = _find_exact(after, title, body)
    if item_id is None or len(after) != len(before) + 1:
        _stop("Provider POST was not verified as exactly one native NoteTemplate.")
    return item_id


async def tp_sync_intermediate_native_notes(
    mode: str = "preview",
    ack_library_id: int | None = None,
    max_items: int = 35,
) -> dict[str, Any]:
    """Preview, lab-probe, or publish 35 exact native NoteTemplates, fail-closed.

    mode=preview: read-only. mode=probe: one LAB NoteTemplate only.
    mode=publish: up to max_items approved notes; requires a verified LAB probe.
    Protected against different coaches, targets, duplicate/unrelated library
    content, drift from the live private plan and ambiguous POST outcomes.
    """
    if mode not in ("preview", "probe", "publish"):
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": "Invalid mode."}
    if type(max_items) is not int or not 1 <= max_items <= 35:
        return {"isError": True, "error_code": "VALIDATION_ERROR",
                "message": "max_items must be between 1 and 35."}
    expected_ack = LAB_ID if mode == "probe" else TARGET_ID if mode == "publish" else None
    if expected_ack is not None and ack_library_id != expected_ack:
        return {"isError": True, "error_code": "PROTECTED_RESOURCE",
                "message": "Explicit exact destination library confirmation required."}
    published: list[dict[str, Any]] = []
    try:
        if not EXPORT_PATH.is_file():
            _stop("Approved manifest not installed with active connector.")
        notes = _validate_manifest(json.loads(EXPORT_PATH.read_text(encoding="utf-8")))
        async with TPClient() as client:
            await _assert_owner_and_libraries(client)
            lab = await _read_items(client, LAB_ID)
            target = await _read_items(client, TARGET_ID)
            done = _validate_target(target, notes)
            if mode == "preview":
                await _assert_live_plan(notes)
                return {"success": True, "stage": "PREVIEW", "native_notes": done,
                        "remaining": 35 - done, "provider_writes": 0}
            if mode == "probe":
                # Existing unrelated LAB cards remain completely untouched.
                provider_id = await _create_verified(client, LAB_ID, CANARY_TITLE, CANARY_BODY)
                return {"success": True, "stage": "LAB_NATIVE_PROBE_PASS",
                        "item_id": provider_id, "provider_type": "NoteTemplate"}
            if _find_exact(lab, CANARY_TITLE, CANARY_BODY) is None:
                _stop("LAB native NoteTemplate canary has not passed.")
            await _assert_live_plan(notes)
            for item in notes:
                if len(published) >= max_items:
                    break
                item_id = await _create_verified(
                    client, TARGET_ID, item["title"], item["description"],
                )
                published.append({"canonical_uid": item["canonical_uid"],
                                  "item_id": item_id})
            final = await _read_items(client, TARGET_ID)
            exact_count = _validate_target(final, notes)
            if exact_count < len(published):
                _stop("Post-publication library readback is incomplete.")
            return {"success": True, "stage": "PUBLISHED" if exact_count == 35
                    else "PARTIAL_VERIFIED", "native_notes": exact_count,
                    "remaining": 35 - exact_count, "verified": published}
    except (NativeNoteStop, OSError, ValueError, TypeError) as exc:
        return {"isError": True, "error_code": "STOP",
                "message": str(exc)[:350], "provider_acknowledged": published,
                "never_retry_ambiguous_post": True}
