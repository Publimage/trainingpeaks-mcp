"""CHASING W01-W04: native in-place Swim distribution, coach-approved.

W01 remains a baseline-test exception (T1500 Tuesday, controlled swim Wednesday,
Friday endurance): moving a 2500 m swim to Monday before T1500 would harm test
comparability. W02–W04 only: move the EASY/TECHNIQUE TUESDAY swim to Monday.
Keep Tuesday's BI and all native Strength, Wednesday swim, Friday swim, all RUN,
long Saturday BI and long Sunday RUN; the Workout Libraries are untouched.

Fail closed, backup initial provider DTO, readback after EVERY PUT, verify all
classic workout IDs, contents, days, notes, provider privacy and plan start.
"""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
PERSON=6682479
PLAN=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
START="2027-01-04"
END="2027-01-31"
CHANGES=[
 {"week":2,"id":4000490220,"source":"2027-01-12","target":"2027-01-11",
  "title":"Aerobico | 2700 m 4x400 regolari","minutes":60,"metres":2700},
 {"week":3,"id":4000591453,"source":"2027-01-19","target":"2027-01-18",
  "title":"Aerobico | 2700 m 4x400 regolari","minutes":60,"metres":2700},
 {"week":4,"id":4000591594,"source":"2027-01-26","target":"2027-01-25",
  "title":"Tecnica | 2300 m 4x300 presa e respirazione","minutes":50,"metres":2300},
]
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w01_w04_mwf_swim_rebalance_backup.json"
def must(v,msg):
 if not v:raise RuntimeError(msg)
def day(w):return str(w.get("workoutDay") or "")[:10]
def stable(w):return {k:v for k,v in w.items() if k not in ("workoutDay","lastModifiedDate")}
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
async def snapshot(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_GET_FAILED")
 h=p.data
 must(h.get("planId")==PLAN and h.get("planPersonId")==PERSON and
      h.get("title")==TITLE and h.get("isPublic") is False and
      h.get("price") in (None,0) and h.get("workoutCount")==276 and
      str(h.get("startDate") or "")[:10]==START,"PLAN_SCOPE_CHANGED")
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
 must(not w.is_error and not n.is_error and isinstance(w.data,list) and
      isinstance(n.data,list) and len(w.data)==39,"FIRST4_COUNT_OR_NOTES_FAILED")
 ids=[x.get("workoutId") for x in w.data]
 must(len(set(ids))==39 and all(type(i) is int and i>0 for i in ids),
      "INVALID_OR_DUPLICATE_WORKOUT_IDS")
 return w.data,digest(n.data)

async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_COACH_OWNER")
  initial,initial_notes=await snapshot(c)
  before={w["workoutId"]:w for w in initial}
  ids=sorted(before)
  # No swim moves on baseline-test week.
  w1test=[w for w in initial if day(w)>="2027-01-04" and day(w)<="2027-01-10" and
          str(w.get("title") or "").startswith("Test |")]
  must({w.get("workoutTypeValueId"):day(w) for w in w1test}==
       {1:"2027-01-05",2:"2027-01-07",3:"2027-01-06"},"BASELINE_W01_CHANGED")
  must(len(CHANGES)==3 and len({e["id"] for e in CHANGES})==3,"WRONG_CHANGE_SET")
  for e in CHANGES:
   w=before.get(e["id"])
   must(w is not None and day(w)==e["source"] and w.get("workoutTypeValueId")==1 and
        w.get("title")==e["title"] and
        abs((w.get("totalTimePlanned") or 0)*60-e["minutes"])<0.02 and
        abs((w.get("distancePlanned") or 0)*1000-e["metres"])<0.02,
        f"SOURCE_SWIM_INVARIANT_FAILED_W{e['week']}")
   must(isinstance(w.get("structure"),dict),"SWIM_BUILDER_MISSING")
   must(not any(x.get("workoutTypeValueId")==1 and day(x)==e["target"] for x in initial),
        f"MONDAY_ALREADY_HAS_SWIM_W{e['week']}")
  must(not BACKUP.exists(),"BACKUP_EXISTS_NO_BLIND_RETRY")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":PLAN,"source_workouts":initial,
        "notes_sha256":initial_notes,"moves":CHANGES},
       ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"SWIM_MWF_PREFLIGHT_PASS","plan":PLAN,"moves":len(CHANGES),
       "W01_test_exception":True,"first4_classic":39,"private":True}),flush=True)
  changed=set()
  for e in CHANGES:
   wlive,ns=await snapshot(c)
   must(ns==initial_notes and sorted(x["workoutId"] for x in wlive)==ids,
        "SOURCE_IDS_OR_NOTES_CHANGED")
   current={v["workoutId"]:v for v in wlive}
   w=current[e["id"]]
   must(day(w)==e["source"] and stable(w)==stable(before[e["id"]]),
        f"MOVE_SOURCE_CHANGED_{e['week']}")
   must(not any(v.get("workoutTypeValueId")==1 and day(v)==e["target"] for v in wlive),
        "TARGET_CONFLICT")
   payload=dict(w); payload["workoutDay"]=e["target"]+str(w["workoutDay"])[10:]
   res=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{e['id']}",
                         json=payload,_retry_on_401=False)
   after,newnotes=await snapshot(c)
   aftermap={v["workoutId"]:v for v in after}
   must(not res.is_error and day(aftermap[e["id"]])==e["target"],
        f"MOVE_UNVERIFIED_W{e['week']}_STOP_NO_RETRY")
   changed.add(e["id"])
   must(sorted(aftermap)==ids and newnotes==initial_notes,
        f"ID_OR_NOTES_DRIFT_W{e['week']}")
   for wid,v in aftermap.items():
    must(stable(v)==stable(before[wid]),f"NON_DATE_CONTENT_CHANGED_{wid}")
    exp=next((x["target"] for x in CHANGES if x["id"]==wid),None) if wid in changed else day(before[wid])
    must(day(v)==exp,f"UNEXPECTED_WORKOUT_DATE_CHANGED_{wid}")
   print(json.dumps({"stage":"SWIM_MOVE_READBACK_PASS","week":e["week"],
       "workout_id":e["id"],"from":e["source"],"to":e["target"],
       "metres":e["metres"],"minutes":e["minutes"]}),flush=True)
  final,notes=await snapshot(c)
  must(notes==initial_notes,"FINAL_NOTES_DRIFT")
  weekly=[]
  for week in range(1,5):
   start=[0,7,14,21][week-1]
   from datetime import date,timedelta
   base=date(2027,1,4)
   monday=(base+timedelta(days=start)).isoformat()
   sw=[w for w in final if w.get("workoutTypeValueId")==1 and
       monday<=day(w)<=(base+timedelta(days=start+6)).isoformat()]
   days=[day(w) for w in sw]
   must(len(sw)==3 and all((w.get("totalTimePlanned") or 0)>0 and
       (w.get("distancePlanned") or 0)>0 and isinstance(w.get("structure"),dict)
       for w in sw),f"SWIM_DURATION_METRES_BUILDER_QA_FAIL_W{week}")
   if week>=2:
    must(days==[(base+timedelta(days=start+j)).isoformat() for j in (0,2,4)],
         f"NON_MWF_W{week}")
   else:
    must(days==[(base+timedelta(days=j)).isoformat() for j in (1,2,4)],
         "W01_EXCEPTION_CHANGED")
   weekly.append({"week":week,"swim_days":days,"swim_metres":sum(w["distancePlanned"] for w in sw)})
  print(json.dumps({"stage":"PASS_W01_W04_SWIM_MWF_REDISTRIBUTION","weekly":weekly,
     "classic_first4":39,"all_plan_workouts":276,"week1_tests_intact":True,
     "non_swim_workouts_untouched":True,"workout_libraries_unchanged":True,
     "athlete_calendars_unchanged":True,"plan_private":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as exc:
  print(json.dumps({"stage":"STOP_NO_BLIND_RETRY","reason":str(exc)[:300]}),flush=True)
  raise
