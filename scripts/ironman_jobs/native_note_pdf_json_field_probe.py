"""Disposable note ONLY. Invalid placeholder data to discover JSON attachment input shape.
All cases must be HTTP 400 and leave note unchanged; never send a real PDF.
"""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886;LAB=684484;NOTE=2655001;ANCHOR=2651317
PREFIX={"planId":LAB,"noteId":NOTE}
BAD="INVALID_NOT_PDF_@@@"
CASES=[
 ("fileData",{"fileData":BAD,"fileName":"probe.pdf"}),
 ("attachmentFileData",{"attachmentFileData":BAD,"fileName":"probe.pdf"}),
 ("data",{"data":BAD,"fileName":"probe.pdf"}),
 ("file",{"file":BAD,"fileName":"probe.pdf"}),
 ("content",{"content":BAD,"fileName":"probe.pdf"}),
 ("fileContents",{"fileContents":BAD,"fileName":"probe.pdf"}),
 ("fileData_object",{"fileData":{"fileName":"probe.pdf","data":BAD}}),
 ("attachmentFileData_object",{"attachmentFileData":{"fileName":"probe.pdf","data":BAD}}),
 ("upload",{"upload":{"fileName":"probe.pdf","data":BAD}}),
 ("attachment",{"attachment":{"fileName":"probe.pdf","data":BAD}}),
]
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  assert me.get("personId")==OWNER
  p=await c.get(f"/plans/v1/plans/{LAB}")
  assert not p.is_error and p.data.get("title")=="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
  assert p.data.get("workoutCount")==1 and p.data.get("isPublic") is False
  async def notes():
   r=await c.get(f"/plans/v1/plans/{LAB}/calendarNote/2027-07-05/2027-07-12")
   assert not r.is_error and isinstance(r.data,list)
   return r.data
  before=await notes()
  assert len(before)==2 and {n["id"] for n in before}=={ANCHOR,NOTE}
  assert not next(n for n in before if n["id"]==NOTE).get("attachments")
  await c._ensure_client()
  token=await c._ensure_access_token();assert token.success
  url=c.base_url+f"/plans/v1/plans/{LAB}/calendarNote/{NOTE}/attachments"
  for label,data in CASES:
   payload={**PREFIX,**data}
   response=await c._client.request("POST",url,headers=c._get_headers(),json=payload,timeout=22)
   print("CASE",label,"STATUS",response.status_code,"REASON",response.text[:240],flush=True)
   after=await notes()
   assert after==before,"STOP_NOTES_CHANGED"
   if response.status_code!=400:
    print("STOP_UNEXPECTED_RESPONSE",flush=True)
    return 2
  print("INVALID_PLACEHOLDER_PROBES_COMPLETED_WITHOUT_WRITES",flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
