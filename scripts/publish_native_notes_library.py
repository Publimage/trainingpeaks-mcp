#!/usr/bin/env python3
"""Create ONLY real TrainingPeaks NoteTemplate library items (never Other cards).

This is an UNVERIFIED provider-route candidate. Read-only by default.
It cannot execute until the custom MCP client is deployed in an authorized
environment. Native Notes remain in the canonical Drive sheet until provider
type+description readback proves exact.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

PRODUCTION_LIBRARY_ID = 3892900
LAB_LIBRARY_ID = 3890637
PROBE_NAME = "[MCP TEST] NoteTemplate library API type-canary"
PROBE_DESCRIPTION = "Disposable native NoteTemplate type canary; no athlete/plan calendar writes."
EXPORT_PATH = Path(__file__).resolve().parents[1] / "data" / "intermediate_native_note_library_queue.json"


def fail(message: str) -> None:
    raise RuntimeError("STOP: " + message)


def validate_export(export: dict[str, Any]) -> list[dict[str, Any]]:
    notes = export.get("notes")
    if export.get("provider_library_id") != PRODUCTION_LIBRARY_ID or not isinstance(notes, list) or len(notes) != 35:
        fail("Unexpected Notes library or canonical note count")
    if export.get("kind") != "SNAPSHOT_NOT_SOURCE_OF_TRUTH" or export.get("desired_native_type") != "NoteTemplate":
        fail("Unverified export source/type")
    titles: set[str] = set()
    uids: set[str] = set()
    for item in notes:
        uid, title, description = item.get("canonical_uid"), item.get("title"), item.get("description")
        if not all(isinstance(x, str) and x.strip() for x in (uid, title, description)):
            fail("Missing UID/title/body")
        if uid in uids or title in titles:
            fail("Duplicate UID or native library title")
        if item.get("qa_status") != "PASS" or item.get("approval_status") != "APPROVED":
            fail("Non-approved Note content")
        if item.get("language") != "it-IT":
            fail("Unexpected language")
        titles.add(title)
        uids.add(uid)
    return notes


def note_template_payload(library_id: int, title: str, description: str) -> dict[str, Any]:
    if library_id not in (LAB_LIBRARY_ID, PRODUCTION_LIBRARY_ID):
        fail("Unknown destination library ID")
    return {
        "exerciseLibraryId": library_id,
        "exerciseLibraryItemType": "NoteTemplate",
        "itemName": title,
        "workoutTypeId": 0,
        "description": description,
    }


def exact_native_note(item: dict[str, Any], title: str, description: str) -> bool:
    return (
        item.get("exerciseLibraryItemType") == "NoteTemplate"
        and item.get("workoutTypeId") == 0
        and item.get("itemName") == title
        and item.get("description") == description
        and item.get("structure") is None
        and item.get("totalTimePlanned") is None
    )


async def list_items(client: Any, library_id: int) -> list[dict[str, Any]]:
    r = await client.get(f"/exerciselibrary/v2/libraries/{library_id}/items")
    if r.is_error or not isinstance(r.data, list):
        fail(f"Library GET failed: {library_id}")
    return r.data


def match_existing(items: list[dict[str, Any]], title: str, description: str) -> int | None:
    matches = [item for item in items if item.get("itemName") == title]
    if len(matches) > 1:
        fail(f"Duplicate library title: {title}")
    if not matches:
        return None
    if not exact_native_note(matches[0], title, description):
        fail(f"Existing item is NOT the approved native NoteTemplate: {title}")
    value = matches[0].get("exerciseLibraryItemId")
    if type(value) is not int or value <= 0:
        fail(f"Missing native provider ID: {title}")
    return value


async def create_checked(client: Any, library_id: int, title: str, description: str) -> int:
    current = await list_items(client, library_id)
    found = match_existing(current, title, description)
    if found is not None:
        return found
    r = await client.post(
        f"/exerciselibrary/v1/libraries/{library_id}/items",
        json=note_template_payload(library_id, title, description),
    )
    if r.is_error:
        fail("Provider rejected native NoteTemplate POST; do not substitute WorkoutTemplate")
    after = await list_items(client, library_id)
    value = match_existing(after, title, description)
    if value is None:
        fail("POST acknowledged without verified native NoteTemplate. STOP; do not retry.")
    return value


async def run(mode: str, ack: int | None) -> dict[str, Any]:
    manifest = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
    notes = validate_export(manifest)
    from tp_mcp.client import TPClient
    async with TPClient() as client:
        lab = await list_items(client, LAB_LIBRARY_ID)
        main = await list_items(client, PRODUCTION_LIBRARY_ID)
        if len({item.get("itemName") for item in main}) != len(main):
            fail("Duplicate names in target Notes library")
        if mode == "dry-run":
            existing = sum(match_existing(main, x["title"], x["description"]) is not None for x in notes)
            return {"stage": "PREVIEW", "native_done": existing, "remaining": 35 - existing,
                    "provider_writes": 0, "provider_type_confirmed": False}
        if mode == "probe":
            if ack != LAB_LIBRARY_ID:
                fail("Exact disposable-lab acknowledgement required")
            provider_id = await create_checked(client, LAB_LIBRARY_ID, PROBE_NAME, PROBE_DESCRIPTION)
            return {"stage": "PROBE_PASS", "provider_id": provider_id,
                    "actual_type": "NoteTemplate"}
        if ack != PRODUCTION_LIBRARY_ID:
            fail("Exact Notes-library acknowledgement required")
        if match_existing(lab, PROBE_NAME, PROBE_DESCRIPTION) is None:
            fail("Native NoteTemplate lab type-canary must pass before production library writes")
        verified: list[dict] = []
        for note in notes:
            provider_id = await create_checked(
                client, PRODUCTION_LIBRARY_ID, note["title"], note["description"]
            )
            verified.append({"canonical_uid": note["canonical_uid"], "item_id": provider_id})
        final = await list_items(client, PRODUCTION_LIBRARY_ID)
        if len(final) != 35 or len(verified) != 35:
            fail("Final cardinality must be exactly 35 true native Notes")
        return {"stage": "FINAL", "success": True, "native_notes": 35,
                "provider_writes_max": 35, "verified": verified}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--probe", action="store_true", help="Only lab type-canary")
    group.add_argument("--execute", action="store_true", help="Create 35 true Notes; requires lab PASS")
    parser.add_argument("--ack-library-id", type=int, default=None)
    args = parser.parse_args()
    mode = "probe" if args.probe else "publish" if args.execute else "dry-run"
    try:
        output = asyncio.run(run(mode, args.ack_library_id))
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"stage": "STOP", "reason": str(exc)[:350],
                          "never_retry_ambiguous_post": True}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
