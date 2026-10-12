"""Private CHASING multi-week run date moves: exact-scope, in-place, non-destructive.

W05-W23: short/easy or prescribed Friday run goes to previously unused Monday.
W07/W09/W11: short easy Thursday run goes to Sunday, Wednesday long run stays.
W13/W19 Sunday reallocation intentionally excluded pending rehearsal recovery QA.
No athlete calendars, note writes, exercise edits, or workout recreation.
"""
from __future__ import annotations
import asyncio,json,hashlib
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
OWNER=2116886
PERSON=6682479
PLAN=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
ANCHOR=date(2027,1,4)
LEDGER=Path("data/chasing_24w_day_ledger_20261012.json")
SUNDAY_WEeks=frozenset({7,9,11})

def must(v,s):
    if not v:raise RuntimeError(s)
def day(x):return str(x.get("workoutDay") or "")[:10]
def uid(x):
    ids=[x[k] for k in ("workoutId","planWorkoutId","id") if type(x.get(k)) is int and x[k]>0]
    must(bool(ids) and len(set(ids))==1,"AMBIGUOUS_WORKOUT_ID")
    return ids[0]
def checksum(a):return hashlib.sha256(json.dumps(a,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
def stable(x):return {k:v for k,v in x.items() if k not in ("workoutDay","lastModifiedDate")}
def d(w,index):
    return (ANCHOR+timedelta(weeks=w-1,days=index)).isoformat()

async def get(c,start,end,expected):
    p=await c.get(f"/plans/v1/plans/{PLAN}")
    must(not p.is_error and isinstance(p.data,dict),"PLAN_GET_FAIL")
    p=p.data
    must(p.get("planId")==PLAN and p.get("planPersonId")==PERSON and
         p.get("title")==TITLE and p.get("isPublic") is False and
         p.get("price") in (None,0) and p.get("workoutCount")==276 and
         str(p.get("startDate") or "")[:10]=="2027-01-05","PLAN_IDENTITY_CHANGED")
    r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{start}/{end}")
    must(not r.is_error and isinstance(r.data,list) and len(r.data)==expected,"BLOCK_COUNT_DRIFT")
    n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{start}/{end}")
    must(not n.is_error and isinstance(n.data,list),"NOTES_UNREADABLE")
    return r.data,checksum(n.data)

async def run(first,last):
    must((first,last) in {(5,8),(9,12),(13,16),(17,20),(21,23)},"UNAUTHORIZED_BLOCK")
    ledger=json.loads(LEDGER.read_text())
    rows=[w for w in ledger["weeks"] if first<=w["week"]<=last]
    must(len(rows)==last-first+1,"CANONICAL_LEDGER_INCOMPLETE")
    expected=sum(bool(day.get(k)) for w in rows for day in w["days"] for k in ("SW","BI","RU"))
    moves=[]
    for w in rows:
        week=w["week"]
        fri=w["days"][4]
        must(fri.get("RU",0)>0,f"NO_FRIDAY_RUN_W{week}")
        must(w["days"][0].get("RU",0)==0,f"MONDAY_NOT_ORIGINALLY_EMPTY_W{week}")
        moves.append({"week":week,"source":d(week,4),"target":d(week,0),
                      "minutes":fri["RU"],"intent":"Friday short run -> Monday"})
        if week in SUNDAY_WEeks:
            thu=w["days"][3]
            must(thu.get("RU",0)>0 and w["days"][6].get("RU",0)==0,
                 f"SUNDAY_REBALANCE_NOT_ELIGIBLE_W{week}")
            moves.append({"week":week,"source":d(week,3),"target":d(week,6),
                          "minutes":thu["RU"],"intent":"Thursday easy run -> Sunday; Wednesday long stays"})
    backup=Path.home()/f".trainingpeaks-mcp/chasing_run_moves_w{first:02d}_w{last:02d}_backup.json"
    start=d(first,0)
    end=d(last+1,0)
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        initial,note_sig=await get(c,start,end,expected)
        initial_ids=sorted(uid(x) for x in initial)
        must(len(set(initial_ids))==expected,"INITIAL_DUPLICATE_IDS")
        originals=[]
        for m in moves:
            hit=[x for x in initial if day(x)==m["source"] and x.get("workoutTypeValueId")==3]
            target=[x for x in initial if day(x)==m["target"] and x.get("workoutTypeValueId")==3]
            must(len(hit)==1 and not target,f"COLLISION_OR_MISSING_W{m['week']}")
            original=hit[0]
            must(m["minutes"]>0 and original.get("workoutTypeValueId")==3,
                 f"SPORT_OR_DURATION_INVALID_W{m['week']}")
            originals.append(original)
        must(not backup.exists(),"BACKUP_EXISTS_NO_BLIND_RETRY")
        backup.parent.mkdir(parents=True,exist_ok=True)
        backup.write_text(json.dumps({"plan":PLAN,"first":first,"last":last,
                 "source_ids":initial_ids,"note_sha256":note_sig,
                 "moves":[{"instruction":m,"before":x} for m,x in zip(moves,originals)]},
                 ensure_ascii=False,indent=2)+"\n")
        print(json.dumps({"stage":"BLOCK_PREFLIGHT_PASS","block":[first,last],
              "expected_classic":expected,"move_count":len(moves),"plan_private":True}),flush=True)
        for i,(m,original) in enumerate(zip(moves,originals)):
            before,_=await get(c,start,end,expected)
            old=[x for x in before if uid(x)==uid(original)]
            must(len(old)==1 and day(old[0])==m["source"],f"MOVE_{i}_SOURCE_DRIFT")
            payload=dict(original)
            payload["workoutDay"]=m["target"]+str(original["workoutDay"])[10:]
            resp=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{uid(original)}",
                            json=payload,_retry_on_401=False)
            after,notes_after=await get(c,start,end,expected)
            moved=[x for x in after if uid(x)==uid(original)]
            must(len(moved)==1 and day(moved[0])==m["target"] and not resp.is_error,
                 f"MOVE_{i}_UNVERIFIED_STOP_NO_RETRY")
            must(stable(moved[0])==stable(original) and notes_after==note_sig and
                 sorted(uid(x) for x in after)==initial_ids,f"MOVE_{i}_INVARIANT_FAIL")
            print(json.dumps({"stage":"MOVE_VERIFIED","week":m["week"],
                      "id":uid(original),"to":m["target"]}),flush=True)
        final,notes_final=await get(c,start,end,expected)
        must(sorted(uid(x) for x in final)==initial_ids and notes_final==note_sig,
             "FINAL_BLOCK_QA_FAILED")
        print(json.dumps({"stage":"BLOCK_QA_PASS","weeks":[first,last],
              "moves":len(moves),"workouts":expected,"all_ids_intact":True,
              "structure_preserved":True,"notes_preserved":True,
              "no_athlete_calendar":True,"no_publication":True}),flush=True)
    return 0
