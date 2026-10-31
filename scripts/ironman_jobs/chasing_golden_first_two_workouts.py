"""Golden-first controlled pilot: exactly one bike & one run; plans use relative W/day."""
import asyncio,json,hashlib
from pathlib import Path
from datetime import date
from tp_mcp.client import TPClient
P=685173;OWNER=2116886;PERSON=6682479
# API provider requires an address date range; these are TRANSPORT ONLY, not plan identity.
API_START="2027-04-26";API_END="2027-06-20"
WEEK1_MONDAY=date(2027,1,4)
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_golden_first_2_pilot_20261013.json"
PAIRS=[(4001081061,3892601,14977038,2,170,21,3,"percentOfFtp"),
       (4001081094,3892602,14977039,3,55,21,3,"percentOfThresholdPace")]
def check(q,msg):
 if not q:raise RuntimeError(msg)
def canonical(v):return {k:x for k,x in v.items() if k!="lastModifiedDate"}
def sha(z):return hashlib.sha256(json.dumps(z,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
def location(w):
 d=date.fromisoformat(str(w.get("workoutDay"))[:10])
 delta=(d-WEEK1_MONDAY).days
 return delta//7+1,delta%7
async def pull(c):
 w=await c.get(f"/plans/v1/plans/{P}/workouts/{API_START}/{API_END}")
 n=await c.get(f"/plans/v1/plans/{P}/calendarNote/{API_START}/{API_END}")
 check(not w.is_error and not n.is_error and len(w.data)==88 and len({z["workoutId"] for z in w.data})==88,"SCOPE_READ")
 return w.data,sha(n.data)
async def main():
 async with TPClient() as c:
  u=await c._get_user_data();check(u.get("personId")==OWNER,"WRONG_OWNER")
  plan=await c.get(f"/plans/v1/plans/{P}");h=plan.data
  check(not plan.is_error and h.get("planId")==P and h.get("planPersonId")==PERSON and
        h.get("isPublic") is False and h.get("workoutCount")==276,"WRONG_PRIVATE_PLAN")
  original,notes=await pull(c);by={w["workoutId"]:w for w in original}
  libs={}
  for lid in (3892601,3892602):
   r=await c.get(f"/exerciselibrary/v2/libraries/{lid}/items")
   check(not r.is_error and isinstance(r.data,list),"LIBRARY_READ")
   libs[lid]={z["exerciseLibraryItemId"]:z for z in r.data}
  patches={}
  for wid,lib,item,sport,minutes,wk,wd,metric in PAIRS:
   a=by.get(wid);t=libs[lib].get(item)
   check(a is not None and t is not None and a.get("workoutTypeValueId")==sport
     and location(a)==(wk,wd) and abs(a["totalTimePlanned"]*60-minutes)<.03
     and (a.get("structure") or {}).get("primaryIntensityMetric")=="rpe","FIRST_PROTOTYPE_SCOPE_"+str(wid))
   s=t.get("structure") or {}
   check(abs(t["totalTimePlanned"]*60-minutes)<.03 and s.get("primaryLengthMetric")=="duration"
      and s.get("primaryIntensityMetric")==metric and s.get("primaryIntensityTargetOrRange")=="range"
      and len(s.get("polyline") or [])>=10 and t.get("itemName","").count("|")==1
      and "RPE" in (t.get("description") or ""),"GOLDEN_TEMPLATE_FAIL_"+str(item))
   expected=[(g.get("type"),[(z.get("name"),z.get("intensityClass"),z.get("length")) for z in g.get("steps",[])])
              for g in a["structure"]["structure"]]
   observed=[(g.get("type"),[(z.get("name"),z.get("intensityClass"),z.get("length")) for z in g.get("steps",[])])
              for g in s["structure"]]
   check(expected==observed,"STRUCTURE_DOSE_CHANGED_"+str(wid))
   for g in s["structure"]:
    for v in g["steps"]:
     check(len(v.get("targets") or [])==1 and 0<v["targets"][0]["maxValue"]<=101,"TARGET_INVALID")
   q=dict(a)
   for k,z in (("title","itemName"),("description","description"),("totalTimePlanned","totalTimePlanned"),
               ("distancePlanned","distancePlanned"),("structure","structure"),("workoutSubTypeId","workoutSubTypeId")):
    q[k]=t.get(z)
   patches[wid]=q
  check(not BACKUP.exists(),"BACKUP_EXISTS_RECONCILE")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":P,"original":original,"notes":notes,
     "pairs":PAIRS},ensure_ascii=False,indent=2)+"\n")
  exp={w["workoutId"]:canonical(w) for w in original}
  print(json.dumps({"stage":"PREFLIGHT_TWO_GOLDEN_PASS","writes":len(patches),"weeks":[21],"no_date_in_plan_identity":True}),flush=True)
  for wid,q in patches.items():
   before,bnotes=await pull(c);m={x["workoutId"]:x for x in before}
   check(bnotes==notes and canonical(m[wid])==exp[wid],"PILOT_PREWRITE_DRIFT")
   v=await c._request("PUT",f"/plans/v1/plans/{P}/workouts/{wid}",json=q,_retry_on_401=False)
   after,anotes=await pull(c);am={x["workoutId"]:x for x in after}
   check(not v.is_error and anotes==notes and canonical(am[wid])==canonical(q),"PILOT_WRITE_FAILED_"+str(wid))
   exp[wid]=canonical(q)
   check(all(canonical(am[k])==z for k,z in exp.items()),"UNEXPECTED_OTHER_CHANGE")
   check(am[wid]["structure"]["primaryIntensityMetric"]==q["structure"]["primaryIntensityMetric"],"METRIC_DRIFT")
   print(json.dumps({"stage":"GOLDEN_COPY_VERIFIED","id":wid,"relative_week":location(am[wid])[0],
    "relative_day":location(am[wid])[1],"metric":am[wid]["structure"]["primaryIntensityMetric"]}),flush=True)
  print(json.dumps({"stage":"PASS_2_GOLDEN_NATIVE_AND_PLAN","writes":2,"unchanged_other_workouts":86,
    "plan_private":True,"no_athlete_writes":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","reason":str(e)[:360]}),flush=True)
  raise
