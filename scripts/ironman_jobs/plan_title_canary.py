"""One-shot disposable TrainingPeaks plan title UPDATE canary and rollback.
Provider writes restricted to lab plan 684484, no athlete calendars.
"""
import asyncio
import json
from tp_mcp.client import TPClient

OWNER=2116886
PLAN=684484
OLD="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
NEW="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09 | TITLE CANARY"
EXPECTED_NOTE_ID=2651317

class Stop(Exception): pass
def must(v, message):
    if not v: raise Stop(message)

async def go():
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER, "WRONG_OWNER")
        async def detail():
            p=await c.get(f"/plans/v1/plans/{PLAN}")
            must(not p.is_error and isinstance(p.data,dict),"PLAN_READ_FAILED")
            return p.data
        async def notes():
            r=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-07-05/2027-07-12")
            must(not r.is_error and isinstance(r.data,list),"NOTES_READ_FAILED")
            return r.data
        p=await detail()
        must(p.get("planId")==PLAN and p.get("title")==OLD and p.get("workoutCount")==1
             and p.get("weekCount")==1 and p.get("isPublic") is False and p.get("price") in (None,0),
             "LAB_SCOPE_CHANGED")
        saved_notes=await notes()
        must(len(saved_notes)==1 and saved_notes[0].get("id")==EXPECTED_NOTE_ID,"LAB_NOTE_CHANGED")
        baseline={k:v for k,v in p.items() if k!="title"}
        baseline_notes=json.dumps(saved_notes,sort_keys=True)
        # Minimal only-title JSON, never full stale provider object or touching plans/week calendar.
        rename=await c._request("PUT",f"/plans/v1/plans/{PLAN}",
                                json={"planId":PLAN,"title":NEW},_retry_on_401=False)
        if rename.is_error:
            print("CANARY_PUT_REJECTED",str(rename.error_code),str(rename.message)[:90],flush=True)
            return 3
        changed=await detail()
        must(changed.get("title")==NEW,"CANARY_PUT_NOT_READBACK")
        must({k:v for k,v in changed.items() if k!="title"}==baseline,"CANARY_DRIFT")
        must(json.dumps(await notes(),sort_keys=True)==baseline_notes,"CANARY_NOTES_DRIFT")
        print("CANARY_CHANGED_VERIFIED",flush=True)
        rollback=await c._request("PUT",f"/plans/v1/plans/{PLAN}",
                                  json={"planId":PLAN,"title":OLD},_retry_on_401=False)
        must(not rollback.is_error,"CANARY_ROLLBACK_ERROR;MANUAL_INSPECTION")
        restored=await detail()
        must(restored==p and json.dumps(await notes(),sort_keys=True)==baseline_notes,
             "CANARY_ROLLBACK_MISMATCH")
        print("CANARY_RESTORED_VERIFIED", "plan:",PLAN,"workouts:1","notes:1",flush=True)
        return 0

if __name__=="__main__":
    try: raise SystemExit(asyncio.run(go()))
    except Stop as e:
        print("STOP_REVIEW",str(e),flush=True)
        raise SystemExit(2)
