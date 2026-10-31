"""Read-only: exact native dual-metric Builder exemplars and current broken pilot candidates."""
import asyncio,json
from tp_mcp.client import TPClient
PLAN=685173;OWNER=2116886
RANGES=[("2027-01-04","2027-02-28"),("2027-03-01","2027-04-25"),("2027-04-26","2027-06-20")]
FOCUS={4001081061,4001081094}
async def main():
 async with TPClient() as c:
  user=await c._get_user_data()
  if user.get("personId")!=OWNER:raise RuntimeError("OWNER_MISMATCH")
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  if p.is_error or p.data.get("planId")!=PLAN or p.data.get("isPublic") is not False:raise RuntimeError("PLAN_SCOPE")
  rows=[]
  for start,end in RANGES:
   r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{start}/{end}")
   if r.is_error:raise RuntimeError("READ_FAIL")
   rows+=r.data
  ex=[w for w in rows if w.get("workoutTypeValueId") in (2,3)
      and ((w.get("structure") or {}).get("primaryIntensityMetric") in ("percentOfFtp","percentOfThresholdPace") or w.get("workoutId") in FOCUS)]
  for w in ex:
   s=w.get("structure") or {}
   x={"stage":"GOLDEN_PROBE","id":w["workoutId"],"title":w.get("title"),"sport":w.get("workoutTypeValueId"),
    "date":w.get("workoutDay"),"minutes":(w.get("totalTimePlanned") or 0)*60,
    "metric":s.get("primaryIntensityMetric"),"target_or_range":s.get("primaryIntensityTargetOrRange"),
    "groups":[{"type":z.get("type"),"reps":z.get("length",{}).get("value"),"steps":[{"name":q.get("name"),
     "duration":q.get("length"),"class":q.get("intensityClass"),"targets":q.get("targets")} for q in z.get("steps") or []]} for z in s.get("structure") or []],
    "description_start":(w.get("description") or "")[:650]}
   print(json.dumps(x,ensure_ascii=False),flush=True)
  print(json.dumps({"stage":"PASS","samples":len(ex),"all":len(rows)}),flush=True)
if __name__=="__main__":asyncio.run(main())
