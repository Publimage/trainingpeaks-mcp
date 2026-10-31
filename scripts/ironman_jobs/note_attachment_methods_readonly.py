"""Read-only GET, HEAD, OPTIONS on note-attachment candidate routes; no POST."""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
PATHS=[
"/plans/v1/plans/684484/calendarNote/2655001/attachments",
"/plans/v1/plans/684602/calendarNote/2653899/attachments",
"/plans/v1/plans/684484/calendarNote/2655001",
]
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  assert isinstance(me,dict) and me.get("personId")==OWNER
  p=await c.get("/plans/v1/plans/684484")
  assert not p.is_error and p.data.get("isPublic") is False
  await c._ensure_client()
  auth=await c._ensure_access_token()
  assert auth.success,"auth unavailable"
  for path in PATHS:
   for method in ["OPTIONS","HEAD","GET"]:
    u=c.base_url+path
    try:
     r=await c._client.request(method=method,url=u,headers=c._get_headers(),timeout=20)
     # Never print response body, token or user email.
     print(json.dumps({"path":path,"method":method,"status":r.status_code,
       "allow":r.headers.get("allow"),"content_type":r.headers.get("content-type"),
       "length":len(r.content)}),flush=True)
    except Exception as ex:
     print("REQUEST_FAILED",path,method,type(ex).__name__,flush=True)
  print("PROVIDER_WRITES:0",flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
