"""READ_ONLY native snapshot of a single disposable lab bicycle Builder."""
import asyncio,json
from datetime import date,timedelta
from tp_mcp.client import TPClient
P=684206;WID=3994992835;OWNER=2116886
async def main():
 async with TPClient() as c:
  me=await c._get_user_data(); assert me.get("personId")==OWNER,"WRONG_OWNER"
  h=await c.get(f"/plans/v1/plans/{P}")
  assert not h.is_error and h.data.get("planId")==P and h.data.get("isPublic") is False and h.data.get("workoutCount")==6 and "[MCP TEST]" in (h.data.get("title") or ""),"NOT_LAB"
  a=date.fromisoformat(str(h.data["startDate"])[:10]);b=a+timedelta(days=6)
  r=await c.get(f"/plans/v1/plans/{P}/workouts/{a.isoformat()}/{b.isoformat()}")
  assert not r.is_error and isinstance(r.data,list),"READ_FAILED"
  x=next((z for z in r.data if z.get("workoutId")==WID),None)
  assert x and x.get("workoutTypeValueId")==2,"MISSING_BIKE"
  print(json.dumps({"state":"LAB_READ_ONLY","plan":P,"id":WID,"title":x.get("title"),"minutes":(x.get("totalTimePlanned") or 0)*60,
   "structure":x.get("structure"),"provider_writes":0},ensure_ascii=False,default=str),flush=True)
if __name__=="__main__":asyncio.run(main())
