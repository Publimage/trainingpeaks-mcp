"""One-shot guarded repair: README FIRST first on W1 Monday of private TEST plan.

Evidence: TrainingPeaks does not offer same-day Note card reorder. On a disposable
plan 684484 a real POST/DELETE canary passed and restored exact original state.
This job safely duplicates the two preceding native notes before deleting their
old IDs, confirms the provider's actual same-day ordering after each operation,
and preserves the original README with TWO binary PDF attachments unchanged.
No athlete calendar, no plan publishing, no other workout/note changes.
After any ambiguous write result STOP; never retry automatically.
"""
from __future__ import annotations
import asyncio
import json
from typing import Any
from tp_mcp.client import TPClient

OWNER = 2116886
PLAN = 684602
PLAN_TITLE = "[MCP TEST] IRONMAN Intermediate Assembly 24W"
FIRST = "2026-10-05"
END = "2027-04-01"
OLD_PHASE = 2653513
OLD_WEEKLY = 2653514
README = 2653899
EXPECTED = {
    OLD_PHASE: "FASE | Calibration / General Development",
    OLD_WEEKLY: "SETTIMANA 1 | Calibrazione e riferimenti",
    README: "README FIRST | INIZIA DA QUI",
}
EXPECTED_ATTACHMENTS = {
    (95193, "IRONMAN_Intermediate_24W_Guida_Settimana_per_Settimana_v1.0.pdf", 169368),
    (95194, "IRONMAN_Intermediate_24W_Guida_Fueling_Nutrizione_v1.0.pdf", 109724),
}

class Stop(Exception):
    pass

def must(ok: bool, why: str):
    if not ok:
        raise Stop(why)

def nid(n: dict[str, Any]) -> int:
    return int(n.get("id") or n.get("calendarNoteId") or n.get("noteId"))

def w1(notes):
    return [n for n in notes if str(n.get("noteDate") or n.get("date") or "")[:10] == FIRST]

def key(n):
    return (str(n.get("title") or ""), str(n.get("description") or ""),
            str(n.get("noteDate") or n.get("date") or "")[:10],
            json.dumps(n.get("attachments") or [], sort_keys=True))

def layout(notes):
    return [nid(n) for n in w1(notes)]

def pdf_signature(note):
    return {
        (int(a.get("id")), str(a.get("fileName")), int(a.get("contentLength")))
        for a in note.get("attachments", [])
    }

async def run():
    log = []
    async with TPClient() as tp:
        me = await tp._get_user_data()
        must(isinstance(me, dict) and me.get("personId") == OWNER, "WRONG_COACH")
        plan = await tp.get(f"/plans/v1/plans/{PLAN}")
        must(not plan.is_error and isinstance(plan.data, dict), "PLAN_READ_FAILED")
        p = plan.data
        must((p.get("planId"), p.get("title"), p.get("weekCount"), p.get("workoutCount"))
             == (PLAN, PLAN_TITLE, 24, 259), "WRONG_PLAN_OR_WORKOUT_DRIFT")
        must(p.get("isPublic") is False and p.get("price") in (None, 0), "PLAN_NOT_PRIVATE")
        must((p.get("startDate") or "")[:10] == "2026-10-06", "PLAN_ANCHOR_CHANGED")
        async def read_notes():
            r = await tp.get(f"/plans/v1/plans/{PLAN}/calendarNote/{FIRST}/{END}")
            must(not r.is_error and isinstance(r.data, list) and all(isinstance(x,dict) for x in r.data),
                 "NOTE_READ_FAILED")
            return r.data

        base = await read_notes()
        must(len(base) == 35 and len({nid(n) for n in base}) == 35, "NOTE_COUNT_OR_IDS_CHANGED")
        original = {nid(n): n for n in base}
        must(set(EXPECTED).issubset(original), "W1_NOTES_MISSING")
        must(layout(base) == [OLD_PHASE, OLD_WEEKLY, README], "W1_PREORDER_DRIFT")
        for note_id, name in EXPECTED.items():
            n = original[note_id]
            must(n.get("title") == name and key(n)[2] == FIRST, "W1_NOTE_WRONG_ID_OR_TITLE")
            must(isinstance(n.get("description"),str) and len(n["description"]) > 30, "NOTE_BODY_MISSING")
            must(n.get("planId") == PLAN, "NOTE_PLAN_SCOPE_DRIFT")
        must(not original[OLD_PHASE].get("attachments") and not original[OLD_WEEKLY].get("attachments"),
             "OLD_NOTES_HAVE_ATTACHMENTS")
        must(pdf_signature(original[README]) == EXPECTED_ATTACHMENTS, "README_PDFS_CHANGED")

        protected = {i:n for i,n in original.items() if i not in (OLD_PHASE,OLD_WEEKLY)}
        # Stage new notes before deleting any original. Never accept a POST twice.
        replacements: dict[int,int] = {}
        removed: set[int] = set()

        def validate(notes, expected_count):
            must(len(notes) == expected_count, "NOTE_COUNT_CHANGED")
            byid = {nid(n):n for n in notes}
            must(len(byid) == len(notes), "DUPLICATE_NOTE_IDS")
            for i,n in protected.items():
                must(i in byid and byid[i] == n, f"PROTECTED_NOTE_CHANGED:{i}")
            for i,n in original.items():
                if i in (OLD_PHASE,OLD_WEEKLY) and i not in removed:
                    must(i in byid and byid[i] == n, f"ORIGINAL_CHANGED:{i}")
            for old,new in replacements.items():
                must(new in byid and key(byid[new]) == key(original[old]), f"REPLACEMENT_MISMATCH:{old}")
                must(byid[new].get("planId") == PLAN, "WRONG_REPLACEMENT_PLAN")
                must(new > README, "NEW_NOTE_NOT_AFTER_README")
            must(pdf_signature(byid[README]) == EXPECTED_ATTACHMENTS, "README_PDF_LOSS")
            return byid

        validate(base,35)
        for old in (OLD_PHASE, OLD_WEEKLY):
            source = original[old]
            payload = {
                "planId": PLAN, "title": source["title"], "noteDate": FIRST,
                "description": source["description"], "attachments": [],
                "standardFormatDate": "Week 1, Monday",
            }
            # This provider route was proven to create a native Training Plan Note.
            res = await tp._request("POST", f"/plans/v1/plans/{PLAN}/calendarNote",
                                    json=payload, _retry_on_401=False)
            if res.is_error:
                raise Stop(f"POST_AMBIGUOUS_OR_REJECTED:{old};readback_before_any_retry")
            current = await read_notes()
            clones = [n for n in w1(current) if nid(n) not in original
                      and nid(n) not in replacements.values()
                      and key(n) == key(source)]
            must(len(clones) == 1, f"POST_CLONE_NOT_UNIQUE:{old}")
            new_id = nid(clones[0])
            replacements[old] = new_id
            validate(current,35+len(replacements))
            must(layout(current) == [OLD_PHASE, OLD_WEEKLY, README]+list(replacements.values()),
                 "CREATED_NOTE_NOT_DISPLAYED_AFTER_README")
            log.append({"stage":"POST_VERIFIED","old":old,"new":new_id})
            print("POST_VERIFIED:", old, "->",new_id, flush=True)

        # A tested, plan-scoped DELETE route. Canaries passed on disposable plan 684484.
        for old in (OLD_PHASE, OLD_WEEKLY):
            r = await tp._request("DELETE",f"/plans/v1/plans/{PLAN}/calendarNote/{old}",
                                  _retry_on_401=False)
            if r.is_error:
                raise Stop(f"DELETE_AMBIGUOUS_OR_REJECTED:{old};readback_before_any_retry")
            removed.add(old)
            now = await read_notes()
            validate(now,35+len(replacements)-len(removed))
            must(old not in {nid(n) for n in now},f"DELETE_NOT_CONFIRMED:{old}")
            log.append({"stage":"DELETE_VERIFIED","old":old})
            print("DELETE_VERIFIED:", old, flush=True)

        final = await read_notes()
        validate(final,35)
        must(layout(final) == [README,replacements[OLD_PHASE],replacements[OLD_WEEKLY]],
             "README_NOT_FIRST")
        p2=await tp.get(f"/plans/v1/plans/{PLAN}")
        must(not p2.is_error and p2.data.get("workoutCount") == 259
             and p2.data.get("weekCount") == 24 and p2.data.get("planId") == PLAN,
             "TRAINING_PLAN_WORKOUTS_CHANGED")
        print("README_FIRST_VERIFIED:",json.dumps({
            "plan_id":PLAN,"week":1,"day":"Monday","notes":35,"workouts":259,
            "order":layout(final),"titles":[n["title"] for n in w1(final)],
            "readme_id_unchanged":README,
            "readme_pdf_attachments":len(original[README]["attachments"]),
            "original_older_ids_removed":[OLD_PHASE,OLD_WEEKLY],
            "replacement_ids":replacements,"other_32_notes_unchanged":True,
        },ensure_ascii=False),flush=True)
        return 0

if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run()))
    except Stop as exc:
        print("STOP_REVIEW:",str(exc),flush=True)
        raise SystemExit(2)
    except Exception as exc:
        print("STOP_REVIEW: unexpected error",type(exc).__name__,str(exc)[:250],flush=True)
        raise SystemExit(2)
