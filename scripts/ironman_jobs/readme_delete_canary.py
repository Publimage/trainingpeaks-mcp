"""Disposable plan-only native CalendarNote DELETE canary for README FIRST repair.

Uses the existing 2026-10-09 disposable DELETE route test plan.
Creates exactly one uniquely named note, validates it, deletes it once,
and verifies complete pre-call plan notes and workouts restored.
NEVER touches the Intermediate plan or any athlete calendar.
"""
from __future__ import annotations
import asyncio
import json
from tp_mcp.client import TPClient

OWNER = 2116886
LAB = 684484
TITLE = "[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
DAY = "2027-07-05"
START = "2027-07-05"
END = "2027-07-12"
ANCHOR_ID = 2651317
CANARY_TITLE = "[MCP TEST] README ORDER DELETE CANARY"
CANARY_BODY = "Transient provider DELETE test. No athlete scheduling."

def note_id(x):
    return int(x.get("id") or x.get("calendarNoteId") or x.get("noteId"))

async def run():
    async with TPClient() as tp:
        me = await tp._get_user_data()
        assert isinstance(me, dict) and me.get("personId") == OWNER, "wrong owner"
        r = await tp.get(f"/plans/v1/plans/{LAB}")
        assert not r.is_error and isinstance(r.data, dict), "no test plan"
        p = r.data
        assert (p.get("planId"), p.get("title"), p.get("workoutCount"), p.get("weekCount")) == (LAB, TITLE, 1, 1), "wrong disposable test plan"
        assert p.get("isPublic") is False and p.get("price") in (None, 0), "unsafe public plan"
        async def notes():
            response = await tp.get(f"/plans/v1/plans/{LAB}/calendarNote/{START}/{END}")
            assert not response.is_error and isinstance(response.data, list), "lab readback unavailable"
            return response.data
        original = await notes()
        assert len(original) == 1 and note_id(original[0]) == ANCHOR_ID, "lab notes changed"
        assert original[0].get("title") == "[MCP TEST] DELETE PROBE | Monday anchor note", "original changed"
        assert not original[0].get("attachments"), "unexpected attachment"
        original_snapshot = json.dumps(original, sort_keys=True)
        payload = {"planId": LAB, "title": CANARY_TITLE, "noteDate": DAY,
                   "description": CANARY_BODY, "attachments": [], "standardFormatDate":"Week 1, Monday"}
        res = await tp._request("POST", f"/plans/v1/plans/{LAB}/calendarNote", json=payload, _retry_on_401=False)
        if res.is_error:
            print("STOP: canary POST uncertain/rejected. Inspect lab, do not retry.")
            return 2
        after_add = await notes()
        mine = [x for x in after_add if x.get("title") == CANARY_TITLE and x.get("description") == CANARY_BODY]
        if len(after_add) != 2 or len(mine) != 1 or note_id(mine[0]) <= ANCHOR_ID or not mine[0].get("noteDate", "").startswith(DAY):
            print("STOP: canary POST readback incorrect, do not retry.")
            return 2
        cid = note_id(mine[0])
        print("CANARY_CREATED:", cid, flush=True)
        deleted = await tp._request("DELETE", f"/plans/v1/plans/{LAB}/calendarNote/{cid}", _retry_on_401=False)
        if deleted.is_error:
            print("STOP: DELETE not confirmed; lab canary ID:", cid, "code:", deleted.error_code, flush=True)
            return 2
        final = await notes()
        if json.dumps(final, sort_keys=True) != original_snapshot:
            print("STOP: post-delete lab notes differ; inspect before any other writes.", flush=True)
            return 2
        final_p = await tp.get(f"/plans/v1/plans/{LAB}")
        if final_p.is_error or final_p.data.get("workoutCount") != 1:
            print("STOP: lab workouts differed.", flush=True)
            return 2
        print("CANARY_DELETE_VERIFIED", "lab:", LAB, "notes:1", "workouts:1", flush=True)
        return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
