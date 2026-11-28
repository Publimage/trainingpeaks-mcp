"""Read-only exact native Builder shape and profile, relative weeks 1..8."""
import asyncio,json
from datetime import date
from tp_mcp.client import TPClient
P=685173
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  if u.get("personId")!=2116886:raise RuntimeError("OWNER")
  p=await c.get(f"/plans/v1/plans/{P}")
  if p.is_error or p.data.get("isPublic") is not False:raise RuntimeError("PLAN")
  r=await c.get(f"/plans/v1/plans/{P}/workouts/2027-01-04/2027-02-28")
  if r.is_error or len(r.data)!=79:raise RuntimeError("READ_79")
  out=[]
  for w in r.data:
   if w["workoutTypeValueId"] not in (2,3):continue
   s=w.get("structure") or {}
   blocks=[{"type":g.get("type"),"repeat":g.get("length"),"steps":[{"n":x.get("name"),"cl":x.get("intensityClass"),"len":x.get("length"),"targets":x.get("targets")} for x in g.get("steps") or []]} for g in s.get("structure") or []]
   d=(date.fromisoformat(str(w["workoutDay"])[:10])-date(2027,1,4)).days
   out.append({"wk":d//7+1,"day":d%7,"id":w["workoutId"],"title":w.get("title"),"sport":w["workoutTypeValueId"],"minutes":round(w["totalTimePlanned"]*60,1),"metric":s.get("primaryIntensityMetric"),"blocks":blocks})
  print(json.dumps({"stage":"PASS","count":len(out),"items":out},ensure_ascii=False),flush=True)
if __name__=="__main__":asyncio.run(main())
