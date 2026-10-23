"""Read-only live comparison of CHASING W07 plan instance against unchanged library mother."""
import asyncio,json
from tp_mcp.client import TPClient
PLAN=685173
ID=4000972961
LIB=3892601
LIBITEM=14963066
async def main():
 async with TPClient() as c:
  user=await c._get_user_data()
  if user.get("personId")!=2116886:raise RuntimeError("WRONG_ACCOUNT")
  a=await c.get("/plans/v1/plans/685173/workouts/2027-02-15/2027-02-21")
  if a.is_error:raise RuntimeError("PLAN_READ_FAILED")
  w=next((z for z in a.data if z.get("workoutId")==ID),None)
  if not w:raise RuntimeError("NO_W07")
  s=w.get("structure") or {}
  blocks=[{"cl":step.get("intensityClass"),"name":step.get("name"),"length":step.get("length"),"targets":step.get("targets")} for g in s.get("structure") or [] for step in g.get("steps") or []]
  print(json.dumps({"stage":"NATIVE_READ","id":ID,"title":w.get("title"),"date_adapter":w.get("workoutDay"),"metric":s.get("primaryIntensityMetric"),"step_count":len(blocks),"blocks":blocks,"graph_points":len(s.get("polyline") or []),"RPE_in_description":"RPE" in (w.get("description") or "")},ensure_ascii=False),flush=True)
if __name__=="__main__":asyncio.run(main())
