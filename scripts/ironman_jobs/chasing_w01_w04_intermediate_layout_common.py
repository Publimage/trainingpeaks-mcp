"""CHASING W01–W04 safe structural recovery, in-place workoutDay only.

Intermediate 684602 is the week-structure reference, not copied sessions.
No Library edits, no athlete calendar, no new/deleted workout, no physiology changes.
All moves go via a vacant Friday RUN 'parking' slot, then restored into the
coach-approved Mon easy / Wed easy-or-test / Sat BI long / Sun RU long.
"""
import asyncio,json,hashlib
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=685173
PERSON=6682479
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
ANCHOR=date(2027,1,4)
FIRST="2027-01-04"
LAST="2027-01-31"
# Each pair is (workout ID, source weekday (Mon=0), destination weekday).
# Friday (4) is vacant in RUN on all four weeks, allowing collision-free moves.
STAGES={
 1:[(4000490168,0,4),(4000490197,6,0),(4000490091,2,6),(4000490168,4,2)],
 2:[(4000490280,2,4),(4000490543,6,2),(4000490280,4,6)],
 3:[(4000591571,0,4),(4000591556,6,0),(4000591494,2,6),(4000591571,4,2)],
 4:[(4000591631,2,4),(4000591981,6,2),(4000591631,4,6)]
}
EXPECTED={
 1:{4000490168:(0,2,55,"Test | 5 km - riferimento corsa"),
    4000490197:(6,0,55,"Aerobico | 55' fondo facile RPE2-3"),
    4000490091:(2,6,65,"Aerobico | 65' fondo facile e tecnica opzionale")},
 2:{4000490280:(2,6,75,"Aerobico | 75' fondo facile e tecnica opzionale"),
    4000490543:(6,2,35,"Aerobico | 35' facile senza affaticamento")},
 3:{4000591571:(0,2,60,"Aerobico | 60' fondo facile con tecnica opzionale"),
    4000591556:(6,0,35,"Aerobico | 35' facile senza affaticamento"),
    4000591494:(2,6,85,"Aerobico | 85' fondo facile e tecnica opzionale")},
 4:{4000591631:(2,6,70,"Aerobico | 70' fondo facile senza tecnica obbligatoria"),
    4000591981:(6,2,35,"Aerobico | 35' facile senza affaticamento")}
}
BACKUP_ROOT=Path.home()/".trainingpeaks-mcp"
def must(x,s):
 if not x:raise RuntimeError(s)
def when(week,wd):
 return (ANCHOR+timedelta(weeks=week-1,days=wd)).isoformat()
def day(w):return str(w.get("workoutDay") or "")[:10]
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
def stable(w):return {k:v for k,v in w.items() if k not in ("workoutDay","lastModifiedDate")}
async def get(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_READ_FAILED")
 z=p.data
 must(z.get("planId")==PLAN and z.get("planPersonId")==PERSON and z.get("title")==TITLE
      and z.get("isPublic") is False and z.get("workoutCount")==276 and
      z.get("price") in (None,0) and str(z.get("startDate") or "")[:10]==FIRST,
      "PLAN_SCOPE_DRIFT")
 r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{FIRST}/{LAST}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{FIRST}/{LAST}")
 must(not r.is_error and not n.is_error and isinstance(r.data,list) and
      isinstance(n.data,list) and len(r.data)==39,"FIRST_FOUR_WEEK_COUNT_DRIFT")
 ids=[x.get("workoutId") for x in r.data]
 must(len(set(ids))==39,"DUPLICATE_WORKOUT_IDS")
 return r.data,digest(n.data)
async def run(week):
 must(week in STAGES,"UNAUTHORIZED_WEEK")
 original_name=BACKUP_ROOT/f"chasing_w{week:02d}_intermediate_structural_relayout_backup.json"
 async with TPClient() as c:
  coach=await c._get_user_data()
  must(isinstance(coach,dict) and coach.get("personId")==OWNER,"WRONG_OWNER")
  before,notes=await get(c)
  id_map={w["workoutId"]:w for w in before}
  for wid,(src,dst,minutes,title) in EXPECTED[week].items():
   x=id_map.get(wid)
   must(x is not None and x.get("workoutTypeValueId")==3 and
        day(x)==when(week,src) and x.get("title")==title and
        abs((x.get("totalTimePlanned") or 0)*60-minutes)<0.01,
        f"ORIGINAL_RUN_ID_DATE_DURATION_CHANGED_{wid}")
  fri=when(week,4)
  must(not any(x.get("workoutTypeValueId")==3 and day(x)==fri for x in before),
       "PARKING_FRIDAY_NOT_EMPTY")
  all_ids=sorted(id_map)
  initial_signature={id:stable(x) for id,x in id_map.items()}
  # Untouched existing W01 baseline, and W02-W04 all template contents.
  must(not original_name.exists(),"BACKUP_ALREADY_EXISTS_NO_BLIND_RETRY")
  BACKUP_ROOT.mkdir(parents=True,exist_ok=True)
  original_name.write_text(json.dumps({
      "plan":PLAN,"week":week,"workouts":before,"notes_sha256":notes,
      "expected":EXPECTED[week],"move_schedule":STAGES[week]},
      ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"STRUCTURAL_PRECHECK_PASS","week":week,
      "steps":len(STAGES[week]),"backup":str(original_name),
      "library_writes":0,"athlete_calendar_writes":0}),flush=True)
  for step,(wid,source_idx,dest_idx) in enumerate(STAGES[week],1):
   live,_=await get(c)
   found=[x for x in live if x.get("workoutId")==wid]
   must(len(found)==1 and day(found[0])==when(week,source_idx),
        f"CURRENT_STEP_{step}_SOURCE_DRIFT")
   must(not [x for x in live if x.get("workoutTypeValueId")==3 and
             day(x)==when(week,dest_idx)],f"CURRENT_STEP_{step}_RUN_TARGET_OCCUPIED")
   x=found[0]
   replacement=dict(x)
   replacement["workoutDay"]=when(week,dest_idx)+str(x["workoutDay"])[10:]
   response=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",
                   json=replacement,_retry_on_401=False)
   readback,read_notes=await get(c)
   m=[v for v in readback if v.get("workoutId")==wid]
   must(not response.is_error and len(m)==1 and day(m[0])==when(week,dest_idx),
        f"STEP_{step}_WRITE_UNVERIFIED_STOP_NO_RETRY")
   must(stable(m[0])==initial_signature[wid],
        f"STEP_{step}_CONTENT_CHANGED")
   must(sorted(z["workoutId"] for z in readback)==all_ids and read_notes==notes,
        f"STEP_{step}_IDS_OR_NOTES_CHANGED")
   # Ensure every unchanged workout retains all fields and date, unless it was
   # already visited by the staged move sequence.
   changed_so_far={x[0] for x in STAGES[week][:step]}
   for v in readback:
    id=v["workoutId"]
    must(stable(v)==initial_signature[id],"UNRELATED_CONTENT_DRIFT")
    if id not in changed_so_far:
     must(day(v)==day(id_map[id]),f"UNRELATED_DATE_CHANGED_{id}")
   print(json.dumps({"stage":"MOVE_READBACK_PASS","week":week,"step":step,
     "workout_id":wid,"source":when(week,source_idx),
     "target":when(week,dest_idx)}),flush=True)
  final,final_notes=await get(c)
  must(final_notes==notes and sorted(x["workoutId"] for x in final)==all_ids,
       "FINAL_INTEGRITY_DRIFT")
  for wid,(_,target,minutes,title) in EXPECTED[week].items():
   x=next(y for y in final if y["workoutId"]==wid)
   must(day(x)==when(week,target) and x["title"]==title,"TARGET_NOT_FINAL")
  must(not any(x.get("workoutTypeValueId")==3 and
       day(x)==when(week,4) for x in final),"PARKING_NOT_EMPTY")
  longs=[x for x in final if day(x)==when(week,6) and
         x.get("workoutTypeValueId")==3]
  must(len(longs)==1 and
       abs(longs[0]["totalTimePlanned"]*60-{1:65,2:75,3:85,4:70}[week])<0.01,
       "SUNDAY_LONG_NOT_VERIFIED")
  mondays=[x for x in final if day(x)==when(week,0)]
  must(any(x.get("workoutTypeValueId")==3 for x in mondays),"MONDAY_INACTIVE")
  tests=[x for x in final if "Test |" in str(x.get("title") or "") and
         when(1,0)<=day(x)<=when(1,6)] if week==1 else []
  if week==1:
   t={x.get("workoutTypeValueId"):day(x) for x in tests}
   must(t=={1:"2027-01-05",2:"2027-01-07",3:"2027-01-06"},
        "BASELINE_TESTS_DATES_CHANGED")
  print(json.dumps({"stage":"PASS_WEEKS_STRUCTURAL_RELAYOUT","week":week,
       "sunday_long_min":{1:65,2:75,3:85,4:70}[week],
       "monday_easy":True,"baseline_tests_preserved":week!=1 or True,
       "classic_workouts_first4":39,"full_plan_workouts":276,
       "strength_untouched":True,"libraries_untouched":True,"private":True}),
       flush=True)
if __name__=="__main__":
 import sys
 try:raise SystemExit(asyncio.run(run(int(sys.argv[1]))))
 except Exception as e:
  print(json.dumps({"stage":"STOP_NO_BLIND_RETRY","reason":str(e)[:260]}),flush=True)
  raise
