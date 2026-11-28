"""Lab-only progressive JSON contract discovery for note attachment POST.

Never send binary; stop immediately on ANY non-400 response, and verify provider
note unchanged after each explicit failed validation.
"""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
LAB=684484
NOTE=2655001
URL=f"/plans/v1/plans/{LAB}/calendarNote/{NOTE}/attachments"
CASES=[
 ("plan_only",{"planId":LAB}),
 ("plan_and_id",{"planId":LAB,"id":NOTE}),
 ("plan_and_note_id",{"planId":LAB,"noteId":NOTE}),
 ("plan_and_calendar_note_id",{"planId":LAB,"calendarNoteId":NOTE}),
]
async def main():
 async with TPClient() as c:
  me=await c._get_user_data();assert me["personId"]==OWNER
  p=await c.get(f"/plans/v1/plans/{LAB}")
  assert not p.is_error and p.data["title"]=="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
  async def notes():
   r=await c.get(f"/plans/v1/plans/{LAB}/calendarNote/2027-07-05/2027-07-12")
   assert not r.is_error and isinstance(r.data,list)
   return r.data
  baseline=await notes()
  assert len(baseline)==2 and {n["id"] for n in baseline}=={2651317,NOTE}
  assert not next(n for n in baseline if n["id"]==NOTE).get("attachments")
  await c._ensure_client()
  tok=await c._ensure_access_token();assert tok.success
  for label,payload in CASES:
   res=await c._client.request("POST",c.base_url+URL,
                              headers=c._get_headers(),json=payload,timeout=25)
   print("JSON_CASE",label,"HTTP",res.status_code,"MSG",res.text[:300],flush=True)
   n2=await notes()
   assert n2==baseline,"STOP_PROVIDER_CHANGED"
   if res.status_code!=400:
    print("STOP_NOT_VALIDATION_400",label,flush=True)
    break
  print("JSON_SCHEMA_PROBE_END",flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
