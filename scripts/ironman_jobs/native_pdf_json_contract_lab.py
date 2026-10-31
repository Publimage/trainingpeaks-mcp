"""Lab-only explicit negative JSON body validation on POST native note attachments.

Empty JSON must be rejected; readback must confirm no attachment created.
"""
import asyncio
from tp_mcp.client import TPClient
OWNER=2116886
LAB=684484
NOTE=2655001
URL=f"/plans/v1/plans/{LAB}/calendarNote/{NOTE}/attachments"
async def main():
 async with TPClient() as c:
  me=await c._get_user_data();assert me["personId"]==OWNER
  p=await c.get(f"/plans/v1/plans/{LAB}")
  assert not p.is_error and p.data["title"]=="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
  async def notes():
   r=await c.get(f"/plans/v1/plans/{LAB}/calendarNote/2027-07-05/2027-07-12")
   assert not r.is_error and isinstance(r.data,list)
   return r.data
  before=await notes()
  assert len(before)==2 and {n["id"] for n in before}=={2651317,NOTE}
  assert not next(n for n in before if n["id"]==NOTE).get("attachments")
  await c._ensure_client()
  token=await c._ensure_access_token();assert token.success
  r=await c._client.request("POST",c.base_url+URL,headers=c._get_headers(),json={},timeout=25)
  print("JSON_PROBE_STATUS",r.status_code,flush=True)
  print("JSON_PROBE_MESSAGE",r.text[:1000],flush=True)
  after=await notes()
  assert after==before,"INVALID_BODY_MAY_HAVE_CHANGED_NOTES"
  assert r.status_code in (400,415,422),"UNEXPECTED_PROVIDER_ACCEPT"
  print("EMPTY_JSON_REJECTED_UNCHANGED",flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
