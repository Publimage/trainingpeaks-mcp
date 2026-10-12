"""Disposable one-workout date-move canary for native Training Plan PUT.
NEVER touches the Chasing plan or athletes. Verifies notes and restores original.
"""
import asyncio
import hashlib
import json
from datetime import date
from pathlib import Path
from tp_mcp.client import TPClient

OWNER=2116886
PLAN=684484
PERSON=None
ID=3995256662
TITLE="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
OLD="2027-07-06"
NEW="2027-07-07"
START="2027-07-05"
END="2027-07-15"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_move_lab_canary_684484.json"

def must(condition, reason):
    if not condition:
        raise RuntimeError(reason)

def wid(x):
    a=[x[k] for k in ("workoutId","planWorkoutId","id") if type(x.get(k)) is int and x[k]>0]
    must(bool(a) and len(set(a))==1,"AMBIGUOUS_ID")
    return a[0]

def day(x):
    return str(x.get("workoutDay") or "")[:10]

def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()

async def read(c):
    p=await c.get(f"/plans/v1/plans/{PLAN}")
    must(not p.is_error and isinstance(p.data,dict),"PLAN_UNREADABLE")
    z=p.data
    must(z.get("planId")==PLAN and z.get("title")==TITLE and z.get("isPublic") is False and
         z.get("price") in (None,0) and z.get("workoutCount")==1 and
         str(z.get("startDate") or "")[:10]==START,"LAB_IDENTITY_CHANGED")
    w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
    must(not w.is_error and isinstance(w.data,list) and len(w.data)==1,"LAB_CONTENT_CHANGED")
    x=w.data[0]
    must(wid(x)==ID,"LAB_ID_CHANGED")
    n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
    must(not n.is_error and isinstance(n.data,list) and len(n.data)==1,"LAB_NOTE_CHANGED")
    return x,digest(n.data)

async def main():
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_COACH")
        original,note=await read(c)
        must(day(original)==OLD,"LAB_NOT_AT_ORIGINAL_DATE")
        must(not BACKUP.exists(),"CANARY_ALREADY_RAN_REVIEW_BACKUP")
        BACKUP.parent.mkdir(parents=True,exist_ok=True)
        BACKUP.write_text(json.dumps({"plan":PLAN,"workout":original,"note_sha256":note},ensure_ascii=False,indent=2)+"\n")
        payload=dict(original)
        payload["workoutDay"]=NEW+str(original["workoutDay"])[10:]
        endpoint=f"/plans/v1/plans/{PLAN}/workouts/{ID}"
        print(json.dumps({"stage":"PREFLIGHT","lab":PLAN,"old":OLD,"new":NEW}),flush=True)
        move=await c._request("PUT",endpoint,json=payload,_retry_on_401=False)
        moved=False
        try:
            current,new_note=await read(c)
            moved=day(current)==NEW
            must(not move.is_error and moved,"DATE_PUT_NOT_VERIFIED")
            must(new_note==note,"NOTE_CHANGED")
            must({k:v for k,v in current.items() if k!="workoutDay"}==
                 {k:v for k,v in original.items() if k!="workoutDay"},"OTHER_FIELDS_CHANGED")
            print(json.dumps({"stage":"MOVED_VERIFIED","same_id":True,"notes_preserved":True}),flush=True)
        finally:
            current,_=await read(c)
            if day(current)!=OLD:
                restore=await c._request("PUT",endpoint,json=original,_retry_on_401=False)
                must(not restore.is_error,"RESTORE_REJECTED_MANUAL_RECOVERY")
            final,final_note=await read(c)
            must(final==original and final_note==note,"RESTORE_NOT_VERIFIED")
            print(json.dumps({"stage":"RESTORED","original_unchanged":True,"date_move_capability":moved}),flush=True)

if __name__=="__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({"stage":"STOP","reason":str(exc)[:250],"blind_retry":False}),flush=True)
        raise
