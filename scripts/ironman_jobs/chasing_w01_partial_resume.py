"""One-time W01 RESUME after provider automatically reanchored the private plan.
Exact recorded partial result: 5k TEST moved from Mon Jan04 to Fri Jan08,
other 38 classic workout dates unchanged. Resume ONLY remaining three moves,
restore Monday easy / plan start Jan04. Uses original immutable backup.
Do NOT rerun initial W01 job.
"""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886;PERSON=6682479;PLAN=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
A="2027-01-04";B="2027-01-31"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w01_intermediate_structural_relayout_backup.json"
STEPS=[
(4000490197,"2027-01-10","2027-01-04"),
(4000490091,"2027-01-06","2027-01-10"),
(4000490168,"2027-01-08","2027-01-06")]
def must(b,s):
 if not b:raise RuntimeError(s)
def day(x):return str(x.get("workoutDay") or "")[:10]
def stable(x):return {k:v for k,v in x.items() if k not in ("workoutDay","lastModifiedDate")}
def checksum(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
async def read(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_NOT_READABLE")
 v=p.data
 must(v.get("planId")==PLAN and v.get("planPersonId")==PERSON and
      v.get("title")==TITLE and v.get("isPublic") is False and
      v.get("workoutCount")==276 and v.get("price") in (None,0),"PLAN_SCOPE_DRIFT")
 r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{A}/{B}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{A}/{B}")
 must(not r.is_error and not n.is_error and isinstance(r.data,list) and
       isinstance(n.data,list) and len(r.data)==39,"FIRST4_DRIFT")
 must(len({w.get("workoutId") for w in r.data})==39,"DUPLICATE_IDS")
 return v,r.data,checksum(n.data)
async def main():
 must(BACKUP.exists(),"ORIGINAL_BACKUP_MISSING")
 backing=json.loads(BACKUP.read_text())
 must(backing.get("plan")==PLAN and backing.get("week")==1,"BACKUP_WRONG_PLAN")
 initial={x["workoutId"]:x for x in backing["workouts"]}
 must(len(initial)==39,"BACKUP_DRIFT")
 async with TPClient() as c:
  u=await c._get_user_data()
  must(isinstance(u,dict) and u.get("personId")==OWNER,"WRONG_OWNER")
  p,current,notes=await read(c)
  live={x["workoutId"]:x for x in current}
  must(set(live)==set(initial) and notes==backing["notes_sha256"],"ORIGINAL_IDS_NOT_MATCHED")
  must(str(p.get("startDate") or "")[:10]=="2027-01-05","PARTIAL_ANCHOR_NOT_JAN05")
  must(day(live[4000490168])=="2027-01-08","TEST_NOT_TEMPORARILY_PARKED")
  must(all(day(v)==("2027-01-08" if id==4000490168 else day(initial[id]))
          and stable(v)==stable(initial[id]) for id,v in live.items()),
       "UNEXPECTED_CHANGE_SINCE_INITIAL_PARTIAL")
  print(json.dumps({"stage":"RESUME_W01_PREFLIGHT_PASS","remaining_puts":3,
                    "source":"verified_partial_with_backup","current_anchor":"2027-01-05"}),flush=True)
  touched={4000490168}
  for idx,(id,src,dst) in enumerate(STEPS,1):
   p,before,_=await read(c)
   live={v["workoutId"]:v for v in before}
   must(day(live[id])==src,"PREWRITE_SOURCE_DRIFT")
   must(not any(x.get("workoutTypeValueId")==3 and day(x)==dst for x in before),
        "RUN_TARGET_COLLISION")
   item=dict(live[id]);item["workoutDay"]=dst+str(item["workoutDay"])[10:]
   res=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{id}",json=item,_retry_on_401=False)
   next_plan,after,next_notes=await read(c)
   present={v["workoutId"]:v for v in after}
   must(not res.is_error and day(present[id])==dst and
        str(next_plan.get("startDate") or "")[:10]=="2027-01-04",
        f"STEP_{idx}_WRITE_OR_REANCHOR_UNVERIFIED")
   touched.add(id)
   must(next_notes==notes and set(present)==set(initial) and
        all(stable(v)==stable(initial[wid]) for wid,v in present.items()),
        f"STEP_{idx}_CONTENT_OR_IDS_DRIFT")
   must(all(day(present[wid])==day(initial[wid]) for wid in present if wid not in touched),
        f"STEP_{idx}_OTHER_DATE_CHANGED")
   print(json.dumps({"stage":"W01_RESUME_STEP_PASS","step":idx,"id":id,"date":dst}),flush=True)
  final_plan,final,final_notes=await read(c)
  live={x["workoutId"]:x for x in final}
  expected={4000490168:"2027-01-06",4000490091:"2027-01-10",4000490197:"2027-01-04"}
  must(all(day(live[id])==dt for id,dt in expected.items()),"TARGET_DATES_FAIL")
  must(str(final_plan.get("startDate") or "")[:10]=="2027-01-04" and
       final_notes==notes and len(live)==39,"FINAL_ANCHOR_OR_COUNT_FAIL")
  test={v.get("workoutTypeValueId"):day(v) for v in live.values()
         if str(v.get("title") or "").startswith("Test |") and
         "2027-01-04"<=day(v)<="2027-01-10"}
  must(test=={1:"2027-01-05",2:"2027-01-07",3:"2027-01-06"},"TESTS_CHANGED")
  print(json.dumps({"stage":"PASS_W01_INTERMEDIATE_LAYOUT","monday_easy_run":"55m",
     "run_test":"Wednesday","sunday_long":"65m",
     "private":True,"classics_first4":39,"plan_workouts":276,
     "other_workout_ids_dates_and_content_unchanged":True,
     "library_writes":0,"athlete_calendar_writes":0}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_NO_RETRY","reason":str(e)[:250]}),flush=True)
  raise
