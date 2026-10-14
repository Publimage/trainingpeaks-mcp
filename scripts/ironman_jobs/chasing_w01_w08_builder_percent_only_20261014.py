"""Conservative quantitative-only Builder retrofit on eligible CHASING W01-W08.
Preserve plan-copy top-level content, all timing/step dose, library, athlete calendars.
Explicit exceptions: W01 pre-tests & baseline tests; W05 retest;
W03/W07 bike quality; W07 diagnostic race brick. No invented quality/race thresholds.
"""
import asyncio,copy,json,hashlib
from datetime import date
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.library import _ensure_structure_preview
P=685173;OWNER=2116886;PERSON=6682479
A="2027-01-04";B="2027-02-28"
START=date(2027,1,4)
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w01_w08_builder_percent_only_20261014_backup.json"
EXCEPT={
 4000490197:"RUN_PRE_5KM",4000489926:"BI_PRE_20MIN",
 4000490168:"RUN_5KM_TEST",4000490118:"BI_20MIN_TEST",
 4000954256:"BI_W05_RETEST",
 4000591505:"BI_W03_QUALITY_NEEDS_APPROVED_FTP_PROFILE",
 4000972961:"BI_W07_STEADY_NEEDS_APPROVED_FTP_PROFILE",
 4000973064:"RU_W07_DIAGNOSTIC_RACE_PACE_NEEDS_INDIVIDUAL_PROFILE"
}
def must(c,s):
 if not c:raise RuntimeError(s)
def stable(w):return {k:v for k,v in w.items() if k!="lastModifiedDate"}
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
def position(w):
 d=(date.fromisoformat(str(w["workoutDay"])[:10])-START).days
 return d//7+1,d%7
def steps(s):
 return [v for g in s["structure"] for v in g.get("steps") or []]
def target(w,step):
 sport=w["workoutTypeValueId"];title=(w.get("title") or "").lower()
 name=(step.get("name") or "").lower();cl=step.get("intensityClass")
 if sport==2:
  if cl=="warmUp":return 50,60
  if cl=="coolDown":return 45,55
  if cl=="rest":return 50,60
  must(cl=="active","UNKNOWN_BIKE_CLASS")
  if "aero" in name:return 65,72
  if "scarico" in title or "recupero" in title:return 55,65
  if any(t in name for t in ("facile","endurance","lt1","fondo","aerob","controll","agile","circolazione","durability")):return 60,70
  raise RuntimeError("BI_UNAPPROVED_ACTIVE_ROLE:"+str(w["workoutId"])+":"+name)
 if sport==3:
  if cl=="warmUp":return 76,82
  if cl=="coolDown":return 70,78
  if cl=="rest":return 70,78
  must(cl=="active","UNKNOWN_RUN_CLASS")
  if "recupero" in title or "recupero" in name:return 70,78
  wk,wd=position(w)
  if wd==6 and (w.get("totalTimePlanned") or 0)*60>=60:return 80,86
  if any(t in name for t in ("fondo","facile","corsa","aerob","sciolto","lento","conversaz","easy")):return 78,84
  raise RuntimeError("RU_UNAPPROVED_ACTIVE_ROLE:"+str(w["workoutId"])+":"+name)
 raise RuntimeError("WRONG_SPORT")
def patch(w):
 wid=w["workoutId"]
 assert wid not in EXCEPT
 s=w.get("structure") or {}
 must(s.get("primaryIntensityMetric")=="rpe","NOT_ORIGINAL_RPE_"+str(wid))
 must(s.get("primaryLengthMetric")=="duration" and s.get("structure"),"NOT_NATIVE_DURATION_"+str(wid))
 old=steps(s);must(old and len(old)<=30,"STEP_COUNT_"+str(wid))
 q=copy.deepcopy(w);n=q["structure"]
 for step in steps(n):
  must(len(step.get("targets") or [])==1,"INVALID_SOURCE_TARGETS_"+str(wid))
  lo,hi=target(w,step)
  step["targets"][0]["minValue"]=lo
  step["targets"][0]["maxValue"]=hi
 n["primaryIntensityMetric"]="percentOfFtp" if w["workoutTypeValueId"]==2 else "percentOfThresholdPace"
 n["primaryIntensityTargetOrRange"]="range"
 n.pop("polyline",None)
 q["structure"]=_ensure_structure_preview(n)
 must(len(q["structure"].get("polyline") or [])>=3,"POLYLINE_MISSING_"+str(wid))
 must(all(q[k]==w[k] for k in w if k!="structure"),"TOP_LEVEL_DRIFT_"+str(wid))
 a=copy.deepcopy(s);b=copy.deepcopy(q["structure"])
 for z in (a,b):
  for key in ("primaryIntensityMetric","primaryIntensityTargetOrRange","polyline"):z.pop(key,None)
  for step in steps(z):step.pop("targets",None)
 must(a==b,"BUILDER_DOSE_DRIFT_"+str(wid))
 return q
async def fetch(c):
 z=await c.get(f"/plans/v1/plans/{P}/workouts/{A}/{B}")
 n=await c.get(f"/plans/v1/plans/{P}/calendarNote/{A}/{B}")
 must(not z.is_error and not n.is_error and len(z.data)==79,"READ_79_DRIFT")
 return z.data,digest(n.data)
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  must(u.get("personId")==OWNER,"WRONG_COACH")
  p=await c.get(f"/plans/v1/plans/{P}");h=p.data
  must(not p.is_error and h.get("planId")==P and h.get("planPersonId")==PERSON and h.get("isPublic") is False and h.get("workoutCount")==276 and "BOZZA" in (h.get("title") or ""),"WRONG_PLAN")
  original,notes=await fetch(c)
  pool=[w for w in original if w.get("workoutTypeValueId") in (2,3)]
  must(len(pool)==55,"W01_W08_BI_RU_NOT_55")
  by={w["workoutId"]:w for w in pool}
  must(all(i in by for i in EXCEPT),"EXCEPT_ID_MISSING")
  patches={}
  for w in pool:
   if w["workoutId"] in EXCEPT:continue
   metric=(w.get("structure") or {}).get("primaryIntensityMetric")
   if metric!="rpe":
    must(metric==("percentOfFtp" if w["workoutTypeValueId"]==2 else "percentOfThresholdPace"),"UNEXPECTED_NONRPE_METRIC_"+str(w["workoutId"]))
    continue
   patches[w["workoutId"]]=patch(w)
  must(35<=len(patches)<=47,"PATCH_COUNT_OUTSIDE_EXPECTED_RANGE_"+str(len(patches)))
  must(not BACKUP.exists(),"BACKUP_EXISTS_RECONCILE_FIRST")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":P,"original":original,"notes_hash":notes,
   "exceptions":EXCEPT,"patched_ids":list(patches)},indent=2,ensure_ascii=False)+"\n")
  expected={w["workoutId"]:stable(w) for w in original}
  print(json.dumps({"stage":"PREFLIGHT_PASS","total":55,"patch":len(patches),"already_quantitative":47-len(patches),"exemptions":EXCEPT}),flush=True)
  for index,(wid,q) in enumerate(patches.items(),1):
   before,note=await fetch(c); bm={w["workoutId"]:w for w in before}
   must(note==notes and stable(bm[wid])==expected[wid],"PREWRITE_DRIFT_"+str(wid))
   res=await c._request("PUT",f"/plans/v1/plans/{P}/workouts/{wid}",json=q,_retry_on_401=False)
   after,anote=await fetch(c);am={w["workoutId"]:w for w in after}
   must(not res.is_error and anote==notes and stable(am[wid])==stable(q),"WRITE_NOT_VERIFIED_"+str(wid))
   expected[wid]=stable(q)
   must(all(stable(am[k])==expected[k] for k in am),"OTHER_WORKOUT_CHANGED_"+str(wid))
   if index%5==0:print(json.dumps({"stage":"VERIFIED_PROGRESS","n":index,"last_id":wid}),flush=True)
  after,nh=await fetch(c)
  must(nh==notes and all(stable(w)==expected[w["workoutId"]] for w in after),"FINAL_DRIFT")
  print(json.dumps({"stage":"PASS_TARGET_ONLY","written":len(patches),"already_quantitative":47-len(patches),"exemptions":list(EXCEPT),"no_athlete_or_library_writes":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","reason":str(e)[:360]}),flush=True)
  raise
