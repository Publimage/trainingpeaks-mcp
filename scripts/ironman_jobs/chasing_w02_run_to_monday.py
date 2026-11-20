"""CHASING private plan W02 one-shot Friday-to-Monday RUN canary.
No deletion, copying, athlete calendar, or change in workout content.
"""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
PERSON=6682479
PLAN=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
SRC="2027-01-15"
DST="2027-01-11"
EXPECTED_MIN=45
SPORT=3
START="2027-01-04"
END="2027-02-01"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w02_run_move_backup.json"

def must(cond,reason):
    if not cond:raise RuntimeError(reason)
def uid(x):
    a=[x[k] for k in ("workoutId","planWorkoutId","id") if type(x.get(k)) is int and x[k]>0]
    must(bool(a) and len(set(a))==1,"AMBIGUOUS_ID")
    return a[0]
def dt(x):return str(x.get("workoutDay") or "")[:10]
def protect(x):
    return {k:v for k,v in x.items() if k not in ("workoutDay","lastModifiedDate")}
def sig(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()

async def read(c):
    p=await c.get(f"/plans/v1/plans/{PLAN}")
    must(not p.is_error and isinstance(p.data,dict),"PLAN_UNREADABLE")
    m=p.data
    must(m.get("planId")==PLAN and m.get("planPersonId")==PERSON
         and m.get("title")==TITLE and m.get("isPublic") is False
         and m.get("price") in (None,0) and m.get("workoutCount")==276
         and str(m.get("startDate") or "")[:10]=="2027-01-05","PLAN_SCOPE_CHANGED")
    r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
    must(not r.is_error and isinstance(r.data,list) and len(r.data)==39,"FIRST_FOUR_WEEKS_NOT_39")
    n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
    must(not n.is_error and isinstance(n.data,list),"NOTE_READ_FAILED")
    return r.data,sig(n.data)

async def main():
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        before,notes=await read(c)
        src=[x for x in before if dt(x)==SRC and x.get("workoutTypeValueId")==SPORT]
        dst=[x for x in before if dt(x)==DST and x.get("workoutTypeValueId")==SPORT]
        must(len(src)==1 and len(dst)==0,"SOURCE_OR_TARGET_CHANGED")
        original=src[0]
        must("45'" in str(original.get("title")) and original.get("workoutTypeValueId")==SPORT,"UNEXPECTED_WORKOUT")
        must(not BACKUP.exists(),"BACKUP_EXISTS_REVIEW")
        BACKUP.parent.mkdir(parents=True,exist_ok=True)
        BACKUP.write_text(json.dumps({"workout":original,"note_sha256":notes,"before_ids":sorted(uid(x) for x in before)},ensure_ascii=False,indent=2)+"\n")
        payload=dict(original);payload["workoutDay"]=DST+str(original["workoutDay"])[10:]
        print(json.dumps({"stage":"PREFLIGHT","plan":PLAN,"from":SRC,"to":DST,"id":uid(original)}),flush=True)
        res=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{uid(original)}",json=payload,_retry_on_401=False)
        after,newnotes=await read(c)
        matches=[x for x in after if uid(x)==uid(original)]
        must(len(matches)==1,"MOVED_ID_LOST")
        moved=matches[0]
        must(not res.is_error and dt(moved)==DST,"PUT_UNVERIFIED_NO_RETRY")
        must(protect(moved)==protect(original),"UNEXPECTED_CONTENT_CHANGE")
        must(newnotes==notes,"NOTE_MISMATCH")
        must(sorted(uid(x) for x in after)==sorted(uid(x) for x in before),"ID_MULTISETS_CHANGED")
        must(len([x for x in after if dt(x)==SRC and x.get("workoutTypeValueId")==SPORT])==0,"SOURCE_NOT_CLEARED")
        print(json.dumps({"stage":"PASS_W02_DATE_MOVE","plan":PLAN,"workout_id":uid(moved),"source":SRC,"target":DST,"all_workout_ids_preserved":True,"all_content_preserved":True,"notes_preserved":True,"private":True}),flush=True)
if __name__=="__main__":
    try:asyncio.run(main())
    except Exception as e:
        print(json.dumps({"stage":"STOP","reason":str(e)[:220],"automatic_retry":False}),flush=True)
        raise
