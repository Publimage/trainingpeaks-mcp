"""Golden-only guarded RPE conversion in disposable plan 684206.
Never touches Beginner public plan 679801. One verified in-place workout mutation.
"""
import asyncio,copy,hashlib,json
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
from tp_mcp.tools.library import _ensure_structure_preview
P=684206;WID=3994992835;OWNER=2116886
BACKUP=Path.home()/".trainingpeaks-mcp/beginner_rpe_gold_lab_684206_20261016_backup.json"
def need(ok,why):
 if not ok:raise RuntimeError(why)
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def stable(w):return {k:v for k,v in w.items() if k!="lastModifiedDate"}
def flat(s):return [z for g in s.get("structure") or [] for z in g.get("steps") or []]
async def read(c,start,end):
 a=await c.get(f"/plans/v1/plans/{P}/workouts/{start}/{end}")
 n=await c.get(f"/plans/v1/plans/{P}/calendarNote/{start}/{end}")
 need(not a.is_error and not n.is_error and isinstance(a.data,list),"LAB_READ_FAILED")
 return a.data,digest(n.data)
def patch(w):
 need(w["workoutId"]==WID and w["workoutTypeValueId"]==2,"WRONG_WORKOUT")
 s=w.get("structure") or {}
 need(s.get("primaryIntensityMetric")=="percentOfFtp","SOURCE_METRIC_NOT_FTP")
 need(s.get("primaryLengthMetric")=="duration","SOURCE_LENGTH_WRONG")
 steps=flat(s)
 need(len(steps)==4,"UNKNOWN_SOURCE_STEP_COUNT")
 expected=[("warmUp",600),("active",300),("rest",300),("coolDown",300)]
 need(all(z.get("intensityClass")==a and (z.get("length") or {}).get("value")==sec for z,(a,sec) in zip(steps,expected)),"UNKNOWN_STEP_STRUCTURE")
 need((w.get("totalTimePlanned") or 0)*60==45,"DURATION_DRIFT")
 q=copy.deepcopy(w);n=q["structure"]
 rpe={"warmUp":(1,2),"active":(6,7),"rest":(1,2),"coolDown":(1,2)}
 for z in flat(n):
  old=z.get("targets") or []
  need(len(old)==1 and old[0].get("minValue") is not None and old[0].get("maxValue") is not None,"INVALID_TARGET_SHAPE")
  low,high=rpe[z["intensityClass"]]
  z["targets"]=[{"minValue":low,"maxValue":high}]
 n["primaryIntensityMetric"]="rpe"
 n["primaryIntensityTargetOrRange"]="range"
 n.pop("polyline",None)
 q["structure"]=_ensure_structure_preview(n)
 need(len(q["structure"].get("polyline") or [])>=5,"NEW_POLYLINE_MISSING")
 need(all(q[k]==w[k] for k in w if k!="structure"),"TOP_LEVEL_CHANGED")
 old=copy.deepcopy(s);new=copy.deepcopy(q["structure"])
 for z in (old,new):
  z.pop("primaryIntensityMetric",None);z.pop("primaryIntensityTargetOrRange",None);z.pop("polyline",None)
  for a in flat(z):a.pop("targets",None)
 need(old==new,"DOSE_STRUCTURE_CHANGED")
 return q
async def main():
 async with TPClient() as c:
  me=await c._get_user_data();need(me.get("personId")==OWNER,"WRONG_ACCOUNT")
  z=await c.get(f"/plans/v1/plans/{P}")
  need(not z.is_error and z.data.get("planId")==P and z.data.get("isPublic") is False and
       z.data.get("workoutCount")==6 and "[MCP TEST]" in (z.data.get("title") or ""),"NOT_DISPOSABLE_LAB")
  anchor=date.fromisoformat(str(z.data["startDate"])[:10]);start=anchor.isoformat();end=(anchor+timedelta(days=6)).isoformat()
  before,nh=await read(c,start,end)
  need(len(before)==6,"SOURCE_CARD_COUNT")
  originals={w["workoutId"]:stable(w) for w in before}
  w=next((x for x in before if x.get("workoutId")==WID),None)
  need(w is not None,"MISSING_TARGET")
  q=patch(w)
  need(not BACKUP.exists(),"BACKUP_EXISTS_CHECK_STATE_FIRST")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":P,"workout":WID,"originals":before,"notes_hash":nh},ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"LAB_BACKUP_WRITTEN","target":WID,"plan":P,"rpe":True,"new_polyline":len(q["structure"]["polyline"])}),flush=True)
  live,hash2=await read(c,start,end)
  need(hash2==nh and all(stable(a)==originals.get(a["workoutId"]) for a in live),"PREWRITE_CONCURRENT_DRIFT")
  res=await c._request("PUT",f"/plans/v1/plans/{P}/workouts/{WID}",json=q,_retry_on_401=False)
  after,hash3=await read(c,start,end)
  need(not res.is_error and hash3==nh,"WRITE_OR_NOTES_ERROR")
  curr={w["workoutId"]:stable(w) for w in after}
  need(set(curr)==set(originals) and all(curr[k]==originals[k] for k in originals if k!=WID),"OTHER_WORKOUT_CHANGED")
  need(curr[WID]==stable(q),"TARGET_READBACK_DRIFT")
  need(curr[WID]["structure"]["primaryIntensityMetric"]=="rpe","TARGET_NOT_RPE")
  print(json.dumps({"stage":"PASS_LAB_GOLDEN_RPE_CONVERSION","plan":P,"target":WID,
       "metric_before":"percentOfFtp","metric_after":"rpe","minutes":45,"reps":3,
       "other_workouts_preserved":5,"notes_preserved":True,"provider_writes":1}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","reason":str(e)[:400]}),flush=True)
  raise
