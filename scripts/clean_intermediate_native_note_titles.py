"""Guarded one-shot cleanup of 35 title prefixes on private Intermediate TEST Training Plan.

Experimental provider plan-scoped PUT route; first update is README canary.
This script NEVER deletes notes, changes descriptions/dates/attachments or edits athlete calendars.
No retry after network ambiguity. Subsequent notes only after successful provider membership readback.
The manifest is a frozen verified snapshot of NOTES_LIBRARY. Regenerate it if library has changed.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tp_mcp.client import TPClient

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data/intermediate_notes_release_manifest.json"
PLAN_ID = 684602
EXPECTED_TITLE = "[MCP TEST] IRONMAN Intermediate Assembly 24W"
EXPECTED_COUNT = 259
FIRST_DAY = date(2026, 10, 5)
END_DAY = FIRST_DAY + timedelta(days=170)
CANARY_ID = 2653899


def emit(o: dict[str, Any]) -> None:
    print(json.dumps(o, ensure_ascii=False), flush=True)


def expected_items() -> list[dict[str, Any]]:
    doc = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    items = doc.get("provider_notes_to_clean")
    if not isinstance(items, list) or len(items) != 35:
        raise ValueError("Expected exact 35 verified native plan notes.")
    if doc.get("expected_notes_count_before") != 35:
        raise ValueError("Manifest count drift")
    if [r.get("note_id") for r in items][0] != CANARY_ID:
        raise ValueError("README must be canary")
    if len({r.get("note_id") for r in items}) != 35:
        raise ValueError("Duplicated provider note identity")
    if len({r.get("uid") for r in items}) != 35:
        raise ValueError("Duplicated canonical note identity")
    if any(
        not isinstance(r.get("note_id"), int)
        or not (r.get("title_before") or "").startswith("[MCP TEST] ")
        or r.get("title_before") != "[MCP TEST] " + r.get("title_after", "")
        or not r.get("date") or not r.get("description")
        or r.get("week") not in range(1, 25)
        or r.get("relative_day") not in range(1, 169)
        for r in items
    ):
        raise ValueError("Malformed/unclean manifest fields")
    if items[0]["uid"] != "IMINT24W-CONTENT-README-FIRST":
        raise ValueError("Unexpected canary UID")
    return items


async def get_state(client: TPClient) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    rp = await client.get(f"/plans/v1/plans/{PLAN_ID}")
    if rp.is_error or not isinstance(rp.data, dict):
        raise RuntimeError("Protected plan unavailable")
    plan = rp.data
    if (
        plan.get("planId") != PLAN_ID
        or plan.get("title") != EXPECTED_TITLE
        or plan.get("workoutCount") != EXPECTED_COUNT
        or plan.get("weekCount") != 24
        or plan.get("isPublic") is not False
        or plan.get("price") not in (None, 0)
    ):
        raise RuntimeError("Protected plan identity/privacy/workout count changed")
    response = await client.get(
        f"/plans/v1/plans/{PLAN_ID}/calendarNote/"
        f"{FIRST_DAY.isoformat()}/{END_DAY.isoformat()}"
    )
    if response.is_error or not isinstance(response.data, list):
        raise RuntimeError("Native plan note membership unavailable")
    if len(response.data) != 35 or any(not isinstance(n, dict) for n in response.data):
        raise RuntimeError("Unexpected native plan note count/shape")
    result: dict[int, dict[str, Any]] = {}
    for n in response.data:
        try:
            id_ = int(n.get("id") or n.get("calendarNoteId") or n.get("noteId"))
        except (ValueError, TypeError):
            raise RuntimeError("Invalid plan note identity")
        if id_ in result:
            raise RuntimeError("Duplicate plan note ID")
        result[id_] = n
    return plan, result


def expected_protected_signature(notes: dict[int, dict[str, Any]]) -> dict[int, tuple[Any, ...]]:
    return {
        id_: (
            n.get("description"),
            (n.get("noteDate") or n.get("date") or "")[:10],
            json.dumps(n.get("attachments", []), sort_keys=True),
            n.get("planId"),
        )
        for id_, n in notes.items()
    }


async def run() -> int:
    if sys.argv[1:] not in ([], ["--execute"]):
        emit({"success": False, "stage": "arguments", "usage": "--execute"})
        return 1
    execute = sys.argv[1:] == ["--execute"]
    try:
        items = expected_items()
        async with TPClient() as client:
            plan, existing = await get_state(client)
            if set(existing) != {item["note_id"] for item in items}:
                raise RuntimeError("Manifest and provider identities mismatch")
            before_sig = expected_protected_signature(existing)
            for item in items:
                note = existing[item["note_id"]]
                if (
                    note.get("description") != item["description"]
                    or (note.get("noteDate") or note.get("date") or "")[:10] != item["date"]
                    or note.get("title") not in (item["title_before"], item["title_after"])
                ):
                    raise RuntimeError(f"Provider note mismatch: {item['uid']}")
            pending = [x for x in items if existing[x["note_id"]].get("title") == x["title_before"]]
            emit({"stage": "preflight", "success": True, "dry_run": not execute,
                  "plan_id": PLAN_ID, "notes": len(items), "pending": len(pending),
                  "readme_present": CANARY_ID in existing, "workouts": plan["workoutCount"]})
            if not execute:
                return 0
            modified = []
            for x in pending:
                note = existing[x["note_id"]]
                if note.get("attachments") not in (None, []):
                    raise RuntimeError("Note has binary attachments: refuse unknown PUT semantics")
                # The plan-scoped REST endpoint is deliberately fixed, never an athlete route.
                # Provider may not support this route; fail on first 404/405, no workaround.
                url = f"/plans/v1/plans/{PLAN_ID}/calendarNote/{x['note_id']}"
                payload = dict(note)
                payload["title"] = x["title_after"]
                payload["planId"] = PLAN_ID
                result = await client._request(
                    "PUT", url, json=payload, _retry_on_401=False
                )
                if result.is_error:
                    emit({"success": False, "stage": "provider_update_rejected",
                          "uid": x["uid"], "error_code": getattr(result, "error_code", None),
                          "already_verified_updates": modified, "do_not_retry": True})
                    return 1
                # Read back complete plan notes after each update. Do not trust HTTP 200 alone.
                _, after = await get_state(client)
                if (
                    expected_protected_signature(after) != before_sig
                    or len(after) != 35
                    or after[x["note_id"]].get("title") != x["title_after"]
                    or any(
                        after[other_id].get("title") != other.get("title")
                        for other_id, other in existing.items()
                        if other_id != x["note_id"]
                    )
                ):
                    emit({"success": False, "stage": "post_write_readback_failed",
                          "uid": x["uid"], "already_verified_updates": modified,
                          "do_not_retry": True})
                    return 1
                existing = after
                modified.append(x["note_id"])
                emit({"stage": "verified", "completed": len(modified),
                      "total": len(pending), "uid": x["uid"],
                      "note_id": x["note_id"]})
            emit({"success": True, "stage": "final", "notes": 35,
                  "prefixes_removed": len(modified),
                  "remaining_prefixes": sum(
                      n.get("title", "").startswith("[MCP TEST] ") for n in existing.values()
                  ), "workouts_preserved": EXPECTED_COUNT})
            return 0
    except Exception as exc:
        emit({"success": False, "stage": "fail_closed",
              "error": str(exc)[:400], "error_type": type(exc).__name__,
              "retry_automatically": False})
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
