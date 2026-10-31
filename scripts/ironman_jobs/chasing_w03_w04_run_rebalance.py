"""W03-W04 private Chasing distribution fixes, no workout recreation.
Move Friday easy RUN to Monday, and W03 short Thursday easy RUN to Sunday.
Keep W03 Wednesday long run and Saturday long bike unchanged.
"""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=685173
PERSON=6682479
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
START="2027-01-04"
END="2027-02-01"
MOVES=[
    {"week":3,"source":"2027-01-22","target":"2027-01-18","minutes":60,"reason":"distribute easy run on Monday"},
    {"week":3,"source":"2027-01-21","target":"2027-01-24","minutes":35,"reason":"easy post-long Saturday, preserve Wed long run"},
    {"week":4,"source":"2027-01-29","target":"2027-01-25","minutes":35,"reason":"deload Monday easy movement"},
]
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w03_w04_moved_run_manifest_backup.json"

def must(v,s):
    if not v:raise RuntimeError(s)
def day(w):return str(w.get("workoutDay") or "")[:10]
def uid(w):
    a=[w[k] for k in ("workoutId","planWorkoutId","id") if type(w.get(k)) is int and w[k]>0]
    must(bool(a) and len(set(a))==1,"AMBIGUOUS_ID")
    return a[0]
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
def content(x):return {k:v for k,v in x.items() if k not in ("workoutDay","lastModifiedDate")}
async def get(c):
    p=await c.get(f"/plans/v1/plans/{PLAN}")
    must(not p.is_error and isinstance(p.data,dict),"UNREADABLE_PLAN")
    q=p.data
    must(q.get("planId")==PLAN and q.get("planPersonId")==PERSON and
         q.get("title")==TITLE and q.get("isPublic") is False and
         q.get("price") in (None,0) and q.get("workoutCount")==276 and
         str(q.get("startDate") or "")[:10]=="2027-01-05","CHASING_PLAN_CHANGED")
    r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
    must(not r.is_error and isinstance(r.data,list) and len(r.data)==39,"FOUR_WEEK_COUNT_DRIFT")
    n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
    must(not n.is_error and isinstance(n.data,list),"NOTE_READ_ERROR")
    return r.data,digest(n.data)
async def main():
    async with TPClient() as c:
        me=await c._get_user_data()
        must(me.get("personId")==OWNER,"WRONG_OWNER")
        initial,notes=await get(c)
        must(len({uid(w) for w in initial})==39,"DUPLICATED_IDS")
        # Prior canary W02 must already be at Monday, not Friday.
        must(len([w for w in initial if day(w)=="2027-01-11" and w.get("workoutTypeValueId")==3])==1,"W02_CANARY_NOT_PRESENT")
        originals=[]
        for m in MOVES:
            a=[w for w in initial if day(w)==m["source"] and w.get("workoutTypeValueId")==3]
            b=[w for w in initial if day(w)==m["target"] and w.get("workoutTypeValueId")==3]
            must(len(a)==1 and not b,f"DATE_COLLISION_W{m['week']}")
            w=a[0]
            must(f"{m['minutes']}'" in str(w.get("title")),f"UNEXPECTED_RUN_W{m['week']}")
            originals.append(w)
        must(not BACKUP.exists(),"BACKUP_ALREADY_EXISTS_NO_RETRY")
        BACKUP.parent.mkdir(parents=True,exist_ok=True)
        BACKUP.write_text(json.dumps({"plan":PLAN,"expected_ids":sorted(uid(x) for x in initial),
             "notes_sha256":notes,"moves":[{"instruction":m,"workout":w} for m,w in zip(MOVES,originals)]},
             ensure_ascii=False,indent=2)+"\n")
        for idx,(m,w) in enumerate(zip(MOVES,originals)):
            before,_=await get(c)
            old=[v for v in before if uid(v)==uid(w)]
            must(len(old)==1 and day(old[0])==m["source"],f"DRIFT_BEFORE_{idx}")
            payload=dict(w)
            payload["workoutDay"]=m["target"]+str(w["workoutDay"])[10:]
            print(json.dumps({"stage":"MOVE_PREFLIGHT","week":m["week"],"id":uid(w),"source":m["source"],"target":m["target"]}),flush=True)
            response=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{uid(w)}",json=payload,_retry_on_401=False)
            after,newnotes=await get(c)
            moved=[v for v in after if uid(v)==uid(w)]
            must(len(moved)==1 and day(moved[0])==m["target"] and not response.is_error,
                 f"WRITE_UNVERIFIED_{idx}_STOP_NO_RETRY")
            must(content(moved[0])==content(w) and newnotes==notes and
                 sorted(uid(v) for v in after)==sorted(uid(v) for v in initial),
                 f"POST_WRITE_CONTENT_CHANGED_{idx}")
            print(json.dumps({"stage":"MOVE_VERIFIED","week":m["week"],"id":uid(w),"target":m["target"]}),flush=True)
        final,finalnotes=await get(c)
        must(sorted(uid(v) for v in final)==sorted(uid(v) for v in initial) and finalnotes==notes,"FINAL_INVARIANT")
        print(json.dumps({"stage":"PASS_W03_W04_DISTRIBUTION","count":39,
              "moves":len(MOVES),"long_wednesday_and_saturday_preserved":True,
              "all_ids_and_content_preserved":True,"private":True}),flush=True)
if __name__=="__main__":
    try:asyncio.run(main())
    except Exception as e:
        print(json.dumps({"stage":"STOP","reason":str(e)[:200],"blind_retry":False}),flush=True)
        raise
