"""Guarded retrofit W09-W24 CHASING plan-instance BI FTP, RU threshold-pace native Builder.
Update W21 BI race target 68-74 -> 71-75 per approved CHASING policy.
Never change earlier W01-W08, titles, RPE text, dates, structures/doses, libraries, athlete calendars.
Exception holds: one Run threshold retest, 8 race diagnostic bricks, 3 W24 activation runs.
Pace+ shift +1 applies ONLY when explicit native Pace+ provenance/base is found;
there are no such identified segments in W09-24 current instances. Never invent.
"""
import asyncio,copy,hashlib,json,re
from datetime import date
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.library import _ensure_structure_preview
P=685173;OWNER=2116886;PERSON=6682479
RANGES=(("2027-01-04","2027-02-28"),("2027-03-01","2027-04-25"),("2027-04-26","2027-06-20"))
START=date(2027,1,4)
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w09_w24_quantitative_targets_only_20261014_backup.json"
RUN_HOLDS={
4001048527:"IM_RUN_DIAGNOSTIC",4001053081:"IM_RUN_DIAGNOSTIC",
4001059176:"RUN_5KM_RETEST",4001059264:"IM_RUN_DIAGNOSTIC",
4001062302:"IM_RUN_DIAGNOSTIC",4001065444:"IM_RUN_DIAGNOSTIC",
4001072135:"IM_RUN_DIAGNOSTIC",4001076980:"RUN_RACE_EXECUTION_INDIVIDUAL",
4001081245:"IM_RUN_DIAGNOSTIC",
4001089853:"RUN_ACTIVATION_NEUROMUSCULAR",
4001089902:"RUN_ACTIVATION_NEUROMUSCULAR",
4001089934:"RUN_ACTIVATION_NEUROMUSCULAR"
}
W21_RACE_ID=4001081215
def need(b,msg):
 if not b:raise RuntimeError(msg)
def stable(w):return {k:v for k,v in w.items() if k!="lastModifiedDate"}
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
def flatten(s):return [v for g in s.get("structure") or [] for v in g.get("steps") or []]
def week(w):return ((date.fromisoformat(str(w["workoutDay"])[:10])-START).days//7)+1
def is_paceplus(name):
 n=(name or "").lower()
 return "pace+" in n or "pace +" in n or "ritmo gara+" in n or "ritmo gara +" in n or "pace plus" in n
def is_im_bike(n):
 a=n.lower()
 return ("im bike pace" in a or "ironman bike pace" in a or "ironman pace" in a)
def target(w,step):
 sp=w["workoutTypeValueId"]
 title=(w.get("title") or "").lower()
 cl=step.get("intensityClass")
 n=(step.get("name") or "").lower()
 if sp==2:
  if cl=="warmUp":return(50,60)
  if cl=="coolDown":return(45,55)
  if cl=="rest":return(55,65)
  need(cl=="active","BI_UNKNOWN_INTENSITY_CLASS_"+str(w["workoutId"]))
  if is_paceplus(n):raise RuntimeError("PACEPLUS_REFERENCE_NOT_VERIFIED_"+str(w["workoutId"]))
  if is_im_bike(n):return(71,75)
  if "aero un gradino sopra easy" in n or "aero endurance" in n:return(65,72)
  if any(z in n for z in ("posizione aero opzionale","fondo","endurance","aerobico","sotto lt1","easy","facile","agile","circolazione","scioltezza","durability")):
   if "pedalata agile" in title and "circolazione" in n:return(50,55)
   if "recupero" in title and "circolazione" in n:return(50,55)
   if "recupero" in title and "facile" in n:return(55,65)
   return(60,70)
  raise RuntimeError("BI_UNKNOWN_ACTIVE_ROLE_"+str(w["workoutId"])+":"+n)
 if sp==3:
  if cl=="warmUp":return(76,82)
  if cl=="coolDown":return(70,78)
  if cl=="rest":return(70,78)
  need(cl=="active","RU_UNKNOWN_INTENSITY_CLASS_"+str(w["workoutId"]))
  if "recupero" in title or "recupero" in n:return(70,78)
  if "lungo" in title or "fondo lungo" in n:return(80,86)
  if any(z in n for z in ("fondo","facile","aerobico","conversazionale","corsa","sciolto","endurance","lento","transizione")):return(78,84)
  raise RuntimeError("RU_UNKNOWN_ACTIVE_ROLE_"+str(w["workoutId"])+":"+n)
 raise RuntimeError("WRONG_SPORT")
def native_delta_only(w):
 old=w.get("structure") or {}
 must=old.get("primaryIntensityMetric")=="rpe" and old.get("primaryLengthMetric")=="duration" and old.get("structure")
 need(must,"SOURCE_NOT_RPE_NATIVE_"+str(w["workoutId"]))
 before=flatten(old)
 need(len(before)>0 and len(before)<45,"INVALID_BUILDER_STEPS_"+str(w["workoutId"]))
 q=copy.deepcopy(w)
 for z in flatten(q["structure"]):
  need(len(z.get("targets") or [])==1,"SOURCE_MISSING_TARGET_"+str(w["workoutId"]))
  lo,hi=target(w,z)
  z["targets"][0]["minValue"]=lo
  z["targets"][0]["maxValue"]=hi
 q["structure"]["primaryIntensityMetric"]="percentOfFtp" if w["workoutTypeValueId"]==2 else "percentOfThresholdPace"
 q["structure"]["primaryIntensityTargetOrRange"]="range"
 q["structure"].pop("polyline",None)
 q["structure"]=_ensure_structure_preview(q["structure"])
 need(len(q["structure"].get("polyline") or [])>=5,"MISSING_NEW_POLYLINE")
 need(all(q[k]==w[k] for k in w if k!="structure"),"TOP_LEVEL_CHANGED")
 a=copy.deepcopy(old);b=copy.deepcopy(q["structure"])
 for st in (a,b):
  for k in ("polyline","primaryIntensityMetric","primaryIntensityTargetOrRange"):st.pop(k,None)
  for z in flatten(st):z.pop("targets",None)
 need(a==b,"BUILDER_NON_TARGET_CHANGED_"+str(w["workoutId"]))
 return q
def w21_race_only(w):
 need(w["workoutId"]==W21_RACE_ID and w["workoutTypeValueId"]==2 and week(w)==21,"WRONG_RACE_W21")
 st=w["structure"];need(st.get("primaryIntensityMetric")=="percentOfFtp","W21_NOT_FTP")
 steps=flatten(st)
 race=[z for z in steps if "ironman pace" in (z.get("name") or "").lower()]
 need(len(race)==4 and all(z.get("targets")==[{"minValue":68,"maxValue":74}] for z in race),"W21_RACE_ORIGINAL_DRIFT")
 q=copy.deepcopy(w)
 for z in flatten(q["structure"]):
  if "ironman pace" in (z.get("name") or "").lower():
   z["targets"][0]["minValue"]=71
   z["targets"][0]["maxValue"]=75
 q["structure"].pop("polyline",None)
 q["structure"]=_ensure_structure_preview(q["structure"])
 need(all(q[k]==w[k] for k in w if k!="structure"),"W21_TOP_LEVEL_DRIFT")
 a=copy.deepcopy(st);b=copy.deepcopy(q["structure"])
 for x in (a,b):
  x.pop("polyline",None)
  for z in flatten(x):
   if "ironman pace" in (z.get("name") or "").lower():z.pop("targets",None)
 need(a==b,"W21_NOT_RACE_ONLY_DELTA")
 return q
async def block(c,i):
 a,b=RANGES[i]
 ws=await c.get(f"/plans/v1/plans/{P}/workouts/{a}/{b}")
 ns=await c.get(f"/plans/v1/plans/{P}/calendarNote/{a}/{b}")
 need(not ws.is_error and not ns.is_error and isinstance(ws.data,list) and isinstance(ns.data,list),"PROVIDER_READ_FAILED")
 return ws.data,digest(ns.data)
async def snapshot(c):
 result=await asyncio.gather(*(block(c,i) for i in range(3)))
 rows=[w for z in result for w in z[0]]
 need(len(rows)==249 and len({w["workoutId"] for w in rows})==249,"PLAN_249_DRIFT")
 return rows,[z[1] for z in result]
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  need(me.get("personId")==OWNER,"WRONG_COACH_OWNER")
  plan=await c.get(f"/plans/v1/plans/{P}")
  h=plan.data
  need(not plan.is_error and h.get("planId")==P and h.get("planPersonId")==PERSON and h.get("isPublic") is False and h.get("workoutCount")==276 and "BOZZA" in (h.get("title") or ""),"WRONG_TARGET_PLAN")
  rows,notes=await snapshot(c)
  rpe=[w for w in rows if week(w)>=9 and w["workoutTypeValueId"] in (2,3) and (w.get("structure") or {}).get("primaryIntensityMetric")=="rpe"]
  need(len(rpe)==106 and sum(w["workoutTypeValueId"]==2 for w in rpe)==56 and sum(w["workoutTypeValueId"]==3 for w in rpe)==50,"METRIC_COUNTS_DRIFT")
  need(all(w["workoutId"] in {v["workoutId"] for v in rpe} for w in rows if w["workoutId"] in RUN_HOLDS),"HOLD_SET_NOT_PRESENT")
  need(all(next(w for w in rows if w["workoutId"]==k)["workoutTypeValueId"]==3 for k in RUN_HOLDS),"HOLD_NOT_RUN")
  need(not any(is_paceplus(z.get("name")) for w in rows if week(w)>=9 and w["workoutTypeValueId"]==2 for z in flatten(w.get("structure") or {})),"PACE_PLUS_EXPLICIT_REQUIRES_SOURCE_REFERENCE")
  candidates={w["workoutId"]:native_delta_only(w) for w in rpe if w["workoutId"] not in RUN_HOLDS}
  need(len(candidates)==94,"CANDIDATE_COUNT_NOT_94_"+str(len(candidates)))
  w21=next(w for w in rows if w["workoutId"]==W21_RACE_ID)
  candidates[W21_RACE_ID]=w21_race_only(w21)
  need(len(candidates)==95,"TOTAL_CANDIDATES_NOT_95")
  need(not any(week(next(w for w in rows if w["workoutId"]==wid))<=8 for wid in candidates),"TOUCHED_EARLY_WEEKS")
  desired={}
  for w in rows:
   desired[w["workoutId"]]=stable(candidates.get(w["workoutId"],w))
  if BACKUP.exists():
   b=json.loads(BACKUP.read_text())
   need(b.get("plan")==P and len(b.get("original",[]))==249 and b.get("notes")==notes,"BACKUP_RECONCILE_REQUIRED")
   orig={w["workoutId"]:stable(w) for w in b["original"]}
   need(all(stable(w) in (orig[w["workoutId"]],desired[w["workoutId"]]) for w in rows),"LIVE_DRIFT_BEFORE_RESUME")
  else:
   BACKUP.parent.mkdir(parents=True,exist_ok=True)
   BACKUP.write_text(json.dumps({"plan":P,"original":rows,"notes":notes,"hold_ids":RUN_HOLDS,"target_ids":list(candidates)},ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"PREFLIGHT_PASS","rpe":106,"bike_rpe_to_ftp":56,"run_rpe_to_threshold":38,"run_holds":RUN_HOLDS,"w21_race_existing_ftp_updated":1,"total":95,"plus_explicit_found":0,"backup":str(BACKUP)}),flush=True)
  current={w["workoutId"]:stable(w) for w in rows}
  pending=[wid for wid in candidates if current[wid]!=desired[wid]]
  for count,wid in enumerate(pending,1):
   w=next(x for x in rows if x["workoutId"]==wid)
   idx=0 if week(w)<=8 else 1 if week(w)<=16 else 2
   before,nh=await block(c,idx)
   state={z["workoutId"]:stable(z) for z in before}
   need(nh==notes[idx] and state[wid]==current[wid],"PREWRITE_DRIFT_"+str(wid))
   q=candidates[wid]
   res=await c._request("PUT",f"/plans/v1/plans/{P}/workouts/{wid}",json=q,_retry_on_401=False)
   after,nh2=await block(c,idx)
   actual={z["workoutId"]:stable(z) for z in after}
   need(nh2==notes[idx],"CALENDAR_NOTES_DRIFT_"+str(wid))
   need(actual[wid]==desired[wid],"POSTWRITE_NOT_VERIFIED_"+str(wid))
   need(all(actual[k]==(desired[k] if k==wid else state[k]) for k in state),"UNRELATED_WORKOUT_MODIFIED_"+str(wid))
   current[wid]=desired[wid]
   if count%10==0:print(json.dumps({"stage":"VERIFIED_PROGRESS","done":count,"remaining":len(pending)-count}),flush=True)
  final,fn=await snapshot(c)
  need(fn==notes and all(stable(w)==desired[w["workoutId"]] for w in final),"FINAL_STATE_DRIFT")
  need(all(week(w)>=9 for w in final if w["workoutId"] in candidates),"EARLY_WEEK_TOUCHED")
  need(all((w.get("structure") or {}).get("primaryIntensityMetric")!="rpe"
     for w in final if w["workoutId"] in candidates),"RPE_NOT_CONVERTED")
  print(json.dumps({"stage":"PASS_95_QUANTITATIVE_DELTA_ONLY","written":len(pending),"total_verified":95,"bike_ftp":56,"run_threshold":38,"w21_ironman_pace_71_75":4,"run_exceptions":12,"paceplus_instances":0,"W01_W08_preserved":True,"unchanged_titles_descriptions":True,"unchanged_library_athlete":True}),flush=True)

if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","reason":str(e)[:450]}),flush=True)
  raise
