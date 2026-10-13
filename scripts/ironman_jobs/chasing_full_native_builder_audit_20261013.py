"""Read-only native TrainingPeaks plan builder audit; no provider writes."""
import asyncio,json,math,collections
from datetime import date,timedelta
from tp_mcp.client import TPClient
P=685173
OWNER=2116886
FOCUS={4001081245,4001086537,4001089818,4001089870,4001089879}
RANGES=[("2027-01-04","2027-02-28"),("2027-03-01","2027-04-25"),("2027-04-26","2027-06-20")]
def day(x):return str(x.get("workoutDay") or "")[:10]
def wk(x):return (date.fromisoformat(day(x))-date(2027,1,4)).days//7+1
def ssummary(w):
  st=w.get("structure")
  if not isinstance(st,dict):return {"native":False,"kind":type(st).__name__,"segments":0}
  seg=st.get("structure")
  if not isinstance(seg,list):return {"native":False,"kind":"no_segments_list","keys":list(st)}
  steps=[]
  for j,g in enumerate(seg):
    for k,t in enumerate(g.get("steps") or []):
      steps.append({"group":j,"step":k,"name":t.get("name"),
                    "length":t.get("length"),
                    "targets":t.get("targets"),
                    "intensityClass":t.get("intensityClass"),"openDuration":t.get("openDuration"),
                    "keys":list(t)})
  last=(seg[-1].get("end") if seg else None)
  target=sum(bool(z.get("targets")) for z in steps)
  missing=[z["name"] for z in steps if not z.get("targets")]
  return {"native":bool(seg),"kind":"structured","segments":len(seg),"steps":len(steps),
          "last_end":last,"primaryLengthMetric":st.get("primaryLengthMetric"),
          "primaryIntensityMetric":st.get("primaryIntensityMetric"),
          "polyline_len":len(st.get("polyline") or []),"targets":target,
          "empty_target_names":missing,"steps_detail":steps}
async def main():
  async with TPClient() as c:
    me=await c._get_user_data()
    if me.get("personId")!=OWNER:raise RuntimeError("OWNER_MISMATCH")
    p=await c.get(f"/plans/v1/plans/{P}")
    if p.is_error or p.data.get("isPublic") is not False or p.data.get("workoutCount")!=276:raise RuntimeError("WRONG_PLAN")
    allrows=[]
    for start,end in RANGES:
      a=await c.get(f"/plans/v1/plans/{P}/workouts/{start}/{end}")
      if a.is_error or not isinstance(a.data,list):raise RuntimeError("BLOCK_READ_FAIL")
      allrows.extend(a.data)
    if len(allrows)!=249 or len({x.get("workoutId") for x in allrows})!=249:raise RuntimeError("COUNT_SCOPE")
    issues=[];stat=collections.Counter();weekly=collections.defaultdict(lambda:collections.Counter())
    for w in allrows:
      wd=wk(w);d=ssummary(w);sport=w.get("workoutTypeValueId")
      stat[(sport,"native" if d["native"] else "missing")]+=1
      weekly[wd]["workouts"]+=1
      if not d["native"] or d.get("steps",0)<1:issues.append({"id":w.get("workoutId"),"week":wd,"date":day(w),"sport":sport,"title":w.get("title"),"error":"MISSING_NATIVE_BUILDER"})
      if d["native"]:
        met=d.get("primaryLengthMetric")
        dur=(w.get("totalTimePlanned") or 0)*3600
        if met=="duration" and isinstance(d.get("last_end"),(float,int)) and abs(d["last_end"]-dur)>2:
          issues.append({"id":w.get("workoutId"),"week":wd,"sport":sport,"title":w.get("title"),"error":"BUILDER_DURATION_MISMATCH","builder_s":d["last_end"],"planned_s":dur})
        if d.get("targets")==0:stat[(sport,"all_targets_empty")]+=1
        if sport==1 and (not w.get("distancePlanned") or not w.get("totalTimePlanned")):issues.append({"id":w.get("workoutId"),"week":wd,"sport":sport,"title":w.get("title"),"error":"SWIM_METERS_OR_DURATION_MISSING"})
      if w.get("workoutId") in FOCUS:
        print(json.dumps({"stage":"FOCUS","id":w.get("workoutId"),"date":day(w),"week":wd,
          "title":w.get("title"),"sport":sport,"duration_hours":w.get("totalTimePlanned"),
          "distance_m":w.get("distancePlanned"),
          "structure":d},ensure_ascii=False,default=str),flush=True)
    print(json.dumps({"stage":"AUDIT_249","counts":{str(k):v for k,v in stat.items()},
      "issues":issues[:100],"issues_total":len(issues),
      "week_counts":{str(w):dict(weekly[w]) for w in sorted(weekly)}},ensure_ascii=False,default=str),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP","error":str(e)[:250]}),flush=True)
  raise
