"""Read-only exact native primaryIntensityMetric and targets of private CHASING vs Intermediate benchmark."""
import asyncio,json,collections
from tp_mcp.client import TPClient
PLANS={685173:249,684602:229}
RANGES=[("2027-01-04","2027-02-28"),("2027-03-01","2027-04-25"),("2027-04-26","2027-06-20")]
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  if u.get("personId")!=2116886:raise RuntimeError("OWNER")
  for pid,count in PLANS.items():
   h=await c.get(f"/plans/v1/plans/{pid}")
   if h.is_error or h.data.get("planId")!=pid or h.data.get("isPublic") is not False:raise RuntimeError("PLAN_SCOPE")
   rows=[]
   for start,end in RANGES:
    r=await c.get(f"/plans/v1/plans/{pid}/workouts/{start}/{end}")
    if r.is_error or not isinstance(r.data,list):raise RuntimeError("READ_SCOPE")
    rows.extend(r.data)
   if len(rows)!=count:raise RuntimeError(f"WRONG_COUNT_{pid}_{len(rows)}")
   summary=collections.Counter(); samples={}; offenders=[]
   for w in rows:
    sport=w.get("workoutTypeValueId")
    st=w.get("structure") or {}
    metric=st.get("primaryIntensityMetric","MISSING")
    summary[(sport,metric)]+=1
    if (sport,metric) not in samples:
     z=next((z for g in st.get("structure",[]) for z in g.get("steps",[]) if z.get("targets")),None)
     samples[(sport,metric)]={"id":w["workoutId"],"title":w.get("title"),"sample_target":z.get("targets") if z else None,"structure_keys":list(st)}
    if sport in (2,3) and (metric=="rpe" or metric=="MISSING"):
     offenders.append({"id":w["workoutId"],"day":str(w.get("workoutDay"))[:10],"sport":sport,"metric":metric,"title":w.get("title")})
   print(json.dumps({"stage":"AUDIT_METRICS","plan":pid,"count":len(rows),
    "counts":{str(k):v for k,v in summary.items()},"samples":{str(k):v for k,v in samples.items()},
    "bike_run_rpe_count":len(offenders),"bike_run_rpe_examples":offenders[:30]},ensure_ascii=False),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:print(json.dumps({"stage":"STOP","reason":str(e)}),flush=True);raise
