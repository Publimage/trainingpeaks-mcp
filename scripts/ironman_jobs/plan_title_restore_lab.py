"""Restore disposable plan title after first canary and report exact field drift."""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
LAB=684484
OLD="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
NEW=OLD+" | TITLE CANARY"
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  assert me.get("personId")==OWNER,"owner"
  async def get():
   r=await c.get(f"/plans/v1/plans/{LAB}")
   assert not r.is_error and isinstance(r.data,dict),"provider"
   return r.data
  p=await get()
  assert p.get("planId")==LAB and p.get("title")==NEW and p.get("workoutCount")==1 and p.get("weekCount")==1
  assert p.get("isPublic") is False and p.get("price") in (None,0),"scope"
  x=await c._request("PUT",f"/plans/v1/plans/{LAB}",json={"planId":LAB,"title":OLD},_retry_on_401=False)
  if x.is_error:
   print("RESTORE_REJECTED",str(x.error_code));return 2
  after=await get()
  print("RESTORE_TITLE",after.get("title")==OLD,"ID",after.get("planId"))
  diffs={k:{"before":str(p.get(k))[:180],"after":str(after.get(k))[:180]}
         for k in set(p)|set(after) if k!="title" and p.get(k)!=after.get(k)}
  print("DIFF_OTHER_FIELDS",json.dumps(diffs,ensure_ascii=False),flush=True)
  print("POST_RESTORE_CORE",json.dumps({k:after.get(k) for k in
   ["planId","title","workoutCount","weekCount","dayCount","isPublic","price","startDate"]},
   ensure_ascii=False),flush=True)
  assert after.get("title")==OLD and after.get("workoutCount")==1 and after.get("weekCount")==1
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
