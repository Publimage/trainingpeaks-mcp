"""Native plan CalendarNotes, exact scoped insertion with provider readback.

Only training plan 685173, 31 pre-approved texts from canonical Google Drive
manifest. UID and Wxx codes are internal NEVER in public title/body.
Uses already-proven plan-scoped POST and GET routes; ZERO workout/library/athlete
writes. Batches must run in sequence; if uncertain, STOP and inspect actual
provider state before new uniquely scoped recovery job.
"""
from __future__ import annotations
import asyncio
import json
import re
from datetime import date, timedelta
from pathlib import Path
from tp_mcp.client import TPClient

PLAN = 685173
OWNER = 2116886
PERSON = 6682479
START = date(2027, 1, 4)
END = "2027-06-23"
PLAN_TITLE = "ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
MANIFEST = Path("data/chasing_24w_native_notes_v1.json")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

def must(condition, reason):
    if not condition:
        raise RuntimeError(reason)

def note_id(row):
    return int(row.get("id") or row.get("calendarNoteId") or row.get("noteId") or 0)

def dt(row):
    return (START + timedelta(weeks=int(row["week"]) - 1,
                              days=int(row["day"]))).isoformat()

def key(row):
    return (row["title"], row["description"], str(row.get("noteDate") or row.get("date") or "")[:10])

def expected_key(row):
    return (row["title"], row["description"], dt(row))

def validate_manifest():
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    must(doc.get("schema") == "CHASING_PLAN_NOTE_NATIVE_V1"
         and doc.get("plan_id") == PLAN
         and doc.get("coach_owner") == OWNER, "MANIFEST_SCOPE_DRIFT")
    notes = doc["notes"]
    must(len(notes) == 31, "MANIFEST_COUNT_DRIFT")
    must([x["uid"] for x in notes] ==
         ["CHS-NOTE-%03d" % i for i in range(1, 32)], "MANIFEST_UID_DRIFT")
    must(all(isinstance(x["title"], str) and "|" in x["title"]
       and not re.search(r"CHS-NOTE-|AF-IT-|\\bW[0-2][0-9]\\b|\\bD[1-7]\\b",x["title"],re.I)
       and not re.search(r"CHS-NOTE-",x["description"],re.I)
       and len(x["description"]) >= 240 and 1 <= x["week"] <= 24
       and 0 <= x["day"] <= 6 for x in notes), "PUBLIC_CODE_OR_CONTENT_INVALID")
    must(len(set(expected_key(x) for x in notes)) == 31, "DUPLICATE_NOTE_KEY")
    return notes

def validate_prefix(actual, approved, expected_count):
    must(len(actual) == expected_count, "UNEXPECTED_NOTE_COUNT_%s_%s" % (len(actual), expected_count))
    must(len({note_id(x) for x in actual}) == expected_count
         and all(note_id(x) > 0 for x in actual), "NOTE_ID_MISSING_OR_DUPLICATED")
    must(all(x.get("planId") == PLAN for x in actual), "NOTE_WRONG_PLAN")
    must(all(not x.get("attachments") for x in actual), "UNEXPECTED_ATTACHMENT")
    expected = sorted(expected_key(x) for x in approved[:expected_count])
    observed = sorted(key(x) for x in actual)
    must(observed == expected, "PROVIDER_NOTE_CONTENT_OR_PLACEMENT_MISMATCH")
    must(all(not re.search(r"CHS-NOTE-|AF-IT-|\\bW[0-2][0-9]\\b", x["title"], re.I)
         for x in actual), "TECH_CODE_IN_PROVIDER_TITLE")

async def run_batch(start_index, stop_index):
    must(0 <= start_index < stop_index <= 31, "BAD_BATCH")
    notes = validate_manifest()
    async with TPClient() as tp:
        user = await tp._get_user_data()
        must(user.get("personId") == OWNER, "OWNER_MISMATCH")
        info = await tp.get("/plans/v1/plans/%d" % PLAN)
        must(not info.is_error and isinstance(info.data, dict), "PLAN_META_READ_FAILED")
        p = info.data
        must(p.get("planId") == PLAN and p.get("planPersonId") == PERSON
             and p.get("title") == PLAN_TITLE and p.get("isPublic") is False
             and p.get("price") in (None,0) and p.get("weekCount") == 24
             and p.get("workoutCount") == 276
             and str(p.get("startDate") or "")[:10] == START.isoformat(), "PLAN_SCOPE_OR_WORKOUT_DRIFT")
        async def get_notes():
            r = await tp.get("/plans/v1/plans/%d/calendarNote/%s/%s" %
                             (PLAN, START.isoformat(), END))
            must(not r.is_error and isinstance(r.data, list), "PROVIDER_NOTE_READ_FAILED")
            return r.data
        before = await get_notes()
        validate_prefix(before, notes, start_index)
        print(json.dumps({"stage": "CHASING_NATIVE_NOTE_PREFLIGHT_PASS",
           "from": start_index+1, "to": stop_index, "existing": len(before),
           "provider_workouts":276, "public_codes":0},ensure_ascii=False),flush=True)
        for i in range(start_index,stop_index):
            row = notes[i]
            body = {
                "planId": PLAN,
                "title": row["title"],
                "noteDate": dt(row),
                "description": row["description"],
                "attachments": [],
                "standardFormatDate": "Week %s, %s" % (row["week"], DAYS[row["day"]])
            }
            result = await tp._request(
                "POST", "/plans/v1/plans/%d/calendarNote" % PLAN,
                json=body, _retry_on_401=False)
            # A POST may have committed despite a timeout/rejected response:
            # NEVER blindly resend. Stop for independent provider reconciliation.
            must(not result.is_error, "POST_RESULT_AMBIGUOUS_CHECK_PROVIDER_%s" % row["uid"])
            current = await get_notes()
            validate_prefix(current, notes, i+1)
            matching = [x for x in current if key(x) == expected_key(row)]
            must(len(matching)==1, "NOTE_NOT_UNIQUE_%s" % row["uid"])
            print(json.dumps({"stage":"CHASING_NOTE_VERIFIED_ONE",
               "internal_uid":row["uid"],"provider_note_id":note_id(matching[0]),
               "week":row["week"],"day":row["day"]+1,
               "title":row["title"]},ensure_ascii=False),flush=True)
        final = await get_notes()
        validate_prefix(final,notes,stop_index)
        newmeta = await tp.get("/plans/v1/plans/%d" % PLAN)
        must(not newmeta.is_error and newmeta.data.get("workoutCount")==276
             and newmeta.data.get("isPublic") is False, "PLAN_DRIFT_AFTER_NOTE_WRITE")
        print(json.dumps({"stage":"CHASING_NOTES_BATCH_VERIFIED",
              "range":[start_index+1,stop_index],"total_provider_notes":len(final),
              "provider_workouts":276,"athlete_writes":0,"library_writes":0,
              "workout_writes":0,"public_codes":0},
              ensure_ascii=False),flush=True)

if __name__ == "__main__":
    raise SystemExit("Import and call run_batch from the fixed entrypoint")
