"""Probe candidate JSON field names for note attachment bytes using invalid data only.

Disposable private Training Plan 684484 Note 2655001; no accepted upload
should be possible with invalid base64. Must inspect note invariants each call.
"""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
LAB=684484
NOTE=2655001
ENDPOINT=f"/plans/v1/plans/{LAB}/calendarNote/{NOTE}/attachments"
INVALID="not%%%valid%%%base64!!!"
CASES=[
 ("fileData_str",{"fileData":INVALID}),
 ("FileData_str",{"FileData":INVALID}),
 ("attachmentFileData",{"attachmentFileData":INVALID}),
 ("data",{"data":INVALID}),
 ("fileContentBase64",{"fileContentBase64":INVALID}),
 ("fileData_object",{"fileData":{"data":INVALID}}),
 ("file_obj",{"file":{"data":INVALID}}),
 ("fileData_with_filename",{"fileName":"not-real.pdf","fileData":INVALID}),
]
async def main():
 async with TPClient() as c:
  me=await c._get_user_data();assert me["personId"]==OWNER
  p=await c.get(f"/plans/v1/plans/{LAB}")
  assert not p.is_error and p.data["title"]=="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
  async def read():
   r=await c.get(f"/plans/v1/plans/{LAB}/calendarNote/2027-07-05/2027-07-12")
   assert not r.is_error and isinstance(r.data,list)
   return r.data
  baseline=await read()
  assert len(baseline)==2 and {n["id"] for n in baseline}=={2651317,NOTE}
  assert not next(n for n in baseline if n["id"]==NOTE).get("attachments")
  await c._ensure_client();tok=await c._ensure_access_token();assert tok.success
  for label,fields in CASES:
   req={"planId":LAB,"noteId":NOTE,**fields}
   res=await c._client.request("POST",c.base_url+ENDPOINT,
                              headers=c._get_headers(),json=req,timeout=20)
   print("CASE",label,"STATUS",res.status_code,"MESSAGE",res.text[:430],flush=True)
   assert await read()==baseline,"STOP_NOTE_CHANGED_AFTER_INVALID_REQUEST"
   if res.status_code!=400:
    print("STOP_NON_400",label,flush=True);break
  print("INVALID_FIELD_PROBE_DONE",flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
