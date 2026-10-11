"""Remove exactly temporary signed-link transport note from disposable TrainingPeaks plan.
Already downloaded the exact PDF and SHA256 verified on cloud; never touch final README.
"""
import asyncio
from tp_mcp.client import TPClient
OWNER=2116886;LAB=684484;NOTE=2655001;ANCHOR=2651317
TITLE="[MCP TEST] IRONMAN INTERMEDIATE V3 PDF TEMP TRANSFER"
DOC="/home/ironman/.local/state/ironman-operator/intermediate-guide-v3.pdf"
SHA="7759224d295123bfdab5203dd82dfc7822228b0a3e60885a6b1003a1b4d7c938"
async def run():
 from pathlib import Path
 import hashlib
 p=Path(DOC)
 assert p.is_file() and p.stat().st_size==396936 and hashlib.sha256(p.read_bytes()).hexdigest()==SHA,"cloud_pdf_missing"
 async with TPClient() as c:
  me=await c._get_user_data()
  assert isinstance(me,dict) and me.get("personId")==OWNER
  plan=await c.get(f"/plans/v1/plans/{LAB}")
  assert not plan.is_error
  assert plan.data.get("title")=="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
  assert plan.data.get("workoutCount")==1 and plan.data.get("isPublic") is False
  async def notes():
   r=await c.get(f"/plans/v1/plans/{LAB}/calendarNote/2027-07-05/2027-07-12")
   assert not r.is_error and isinstance(r.data,list)
   return r.data
  items=await notes()
  assert len(items)==2 and {x["id"] for x in items}=={ANCHOR,NOTE}
  n=next(x for x in items if x["id"]==NOTE)
  assert n.get("title")==TITLE and n.get("description","").startswith("SIGNED_READ_URI=")
  assert "\nSHA256="+SHA in n.get("description","")
  d=await c._request("DELETE",f"/plans/v1/plans/{LAB}/calendarNote/{NOTE}",_retry_on_401=False)
  if d.is_error:
   print("DELETE_REJECTED_CHECK_READBACK",str(d.error_code));return 2
  after=await notes()
  assert len(after)==1 and after[0]["id"]==ANCHOR
  print("TEMP_SIGNED_URL_NOTE_REMOVED_VERIFIED", "id",NOTE,"remaining",1,"pdf_cloud_staged",True,flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(run()))
