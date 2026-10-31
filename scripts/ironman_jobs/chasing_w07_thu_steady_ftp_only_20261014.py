"""CHASING W07 Thu Bike 130' steady: exact plan-instance-only FTP Builder correction.
No text, RPE, title, time, block, week/day, library, athlete or other workout changes.
"""
import asyncio,copy,json,hashlib
from datetime import date
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.library import _ensure_structure_preview

PLAN=685173; OWNER=2116886; PERSON=6682479
WID=4000972961; DATE="2027-02-18"
START="2027-01-04"; END="2027-02-28"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w07_thu_steady_ftp_only_20261014_backup.json"
EXPECTED=(("warmUp",900,(50,60)),("active",480,(80,85)),("rest",720,(55,65)),("active",2700,(60,70)),("coolDown",600,(45,55)))

def need(b,reason):
 if not b:raise RuntimeError(reason)
def canon(w):return {k:v for k,v in w.items() if k!="lastModifiedDate"}
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
def flat(s):return [v for g in s.get("structure") or [] for v in g.get("steps") or []]
async def read(c):
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
 need(not w.is_error and not n.is_error and len(w.data)==79,"READ_OR_COUNT")
 return w.data,digest(n.data)
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  need(u.get("personId")==OWNER,"WRONG_COACH")
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  h=p.data
  need(not p.is_error and h.get("planId")==PLAN and h.get("planPersonId")==PERSON and h.get("isPublic") is False and h.get("workoutCount")==276 and "BOZZA" in (h.get("title") or ""),"WRONG_PLAN")
  rows,nh=await read(c);by={w["workoutId"]:w for w in rows}
  need(WID in by,"WID_MISSING")
  w=by[WID]
  need(str(w.get("workoutDay"))[:10]==DATE and (date.fromisoformat(DATE)-date.fromisoformat(START)).days==45,"WRONG_RELATIVE_WEEK_DAY")
  need(w.get("workoutTypeValueId")==2 and abs(w.get("totalTimePlanned")*60-130)<.001 and w.get("title")=="Steady | 130' 3x8' RPE4-5 +12' recupero","WRONG_WORKOUT")
  need("CODICE WORKOUT" not in (w.get("description") or "") and "RPE4" in (w.get("description") or "").replace("–","").replace(" ",""),"DESCRIPTION_DRIFT")
  original=w.get("structure") or {}
  need(original.get("primaryIntensityMetric")=="rpe" and original.get("primaryLengthMetric")=="duration","METRIC_ALREADY_CHANGED_RECONCILE")
  ss=flat(original)
  need(len(ss)==5,"EXPECTED_5_SOURCE_STEPS")
  for i,(cl,sec,(lo,hi)) in enumerate(EXPECTED):
   step=ss[i]
   need(step.get("intensityClass")==cl and step.get("length")=={"value":sec,"unit":"second"},"STEP_ROLE_OR_DURATION_"+str(i))
   need(len(step.get("targets") or [])==1,"SOURCE_TARGET_MISSING_"+str(i))
  q=copy.deepcopy(w);struct=q["structure"];vs=flat(struct)
  for step,(cl,sec,(lo,hi)) in zip(vs,EXPECTED):
   step["targets"][0]["minValue"]=lo
   step["targets"][0]["maxValue"]=hi
  struct["primaryIntensityMetric"]="percentOfFtp"
  struct["primaryIntensityTargetOrRange"]="range"
  struct.pop("polyline",None)
  q["structure"]=_ensure_structure_preview(struct)
  need(len(q["structure"].get("polyline") or [])>=10,"POLYLINE_INCOMPLETE")
  need({k:v for k,v in q.items() if k!="structure"}=={k:v for k,v in w.items() if k!="structure"},"TOP_LEVEL_CHANGED")
  a=copy.deepcopy(original);b=copy.deepcopy(q["structure"])
  for obj in (a,b):
   for k in ("primaryIntensityMetric","primaryIntensityTargetOrRange","polyline"):obj.pop(k,None)
   for step in flat(obj):step.pop("targets",None)
  need(a==b,"UNEXPECTED_BUILDER_DOSE_DELTA")
  need(not BACKUP.exists(),"BACKUP_ALREADY_EXISTS_RECONCILE")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":PLAN,"workout_id":WID,"original":w,"other_workouts_hash":digest([canon(z) for z in rows if z["workoutId"]!=WID]),"notes_hash":nh},ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"PREFLIGHT_PASS","plan":PLAN,"id":WID,"week":7,"day":"THU","target":"80-85%FTP","steps":EXPECTED}),flush=True)
  res=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{WID}",json=q,_retry_on_401=False)
  after,nh2=await read(c)
  aft={z["workoutId"]:z for z in after}
  need(not res.is_error and nh2==nh,"WRITE_OR_NOTES_FAILED")
  need(canon(aft[WID])==canon(q),"TARGET_IN_PLACE_NOT_EXACT")
  need(all(canon(aft[z["workoutId"]])==canon(z) for z in rows if z["workoutId"]!=WID),"OTHER_WORKOUT_CHANGED")
  need(aft[WID]["structure"]["primaryIntensityMetric"]=="percentOfFtp","METRIC_NOT_FTP")
  need([(v["targets"][0]["minValue"],v["targets"][0]["maxValue"]) for v in flat(aft[WID]["structure"])]==[z[2] for z in EXPECTED],"TARGETS_INCORRECT")
  print(json.dumps({"stage":"PASS_ONE_IN_PLACE_VERIFIED","id":WID,"metric":"percentOfFtp","steady_target":"80-85","other_workouts_unchanged":78,"notes_unchanged":True,"text_unchanged":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","error":str(e)[:400]}),flush=True)
  raise
