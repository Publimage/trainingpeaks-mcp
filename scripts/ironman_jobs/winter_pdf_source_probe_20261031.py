"""Read-only verified search for source Winter START PDF provider-download path."""
import asyncio,hashlib,json
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=689369
NOTE=2685704
ATT=105393
PATHS=[
f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/attachments/{ATT}",
f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/attachments/{ATT}/download",
f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/attachment/{ATT}",
f"/files/v1/attachments/{ATT}",
f"/files/v1/attachments/{ATT}/download",
f"/fitness/v1/attachments/{ATT}",
f"/files/v2/attachments/{ATT}",
f"/fitness/v6/attachments/{ATT}",
f"/plans/v1/plans/{PLAN}/attachments/{ATT}",
]
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  if not isinstance(me,dict) or me.get("personId")!=OWNER:raise RuntimeError("WRONG_OWNER")
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  if p.is_error or p.data.get("workoutCount")!=74:raise RuntimeError("SOURCE_PLAN_CHANGED")
  n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-01-04")
  if n.is_error:raise RuntimeError("SOURCE_NOTE_FAILED")
  src=[x for x in n.data if int(x.get("id") or x.get("calendarNoteId"))==NOTE]
  if len(src)!=1 or not any(int(a.get("id"))==ATT and int(a.get("contentLength"))==407035 for a in src[0].get("attachments") or []):raise RuntimeError("SOURCE_ATTACHMENT_CHANGED")
  await c._ensure_client()
  t=await c._ensure_access_token()
  if not t.success:raise RuntimeError("AUTH_UNAVAILABLE")
  for path in PATHS:
   try:
    r=await c._client.get(c.base_url+path,headers=c._get_headers(),timeout=16,follow_redirects=False)
    j=None
    try:j=r.json()
    except Exception:pass
    meta={"route":path,"status":r.status_code,"kind":r.headers.get("content-type"),"size":len(r.content)}
    if r.content.startswith(b"%PDF-"):meta["sha256"]=hashlib.sha256(r.content).hexdigest()
    if isinstance(j,dict):meta["jsonKeys"]=list(j)[:10]
    print(json.dumps(meta,ensure_ascii=False),flush=True)
   except Exception as e:print(json.dumps({"route":path,"exception":type(e).__name__}),flush=True)
  print("PROVIDER_WRITES:0",flush=True)
if __name__=="__main__":asyncio.run(main())
