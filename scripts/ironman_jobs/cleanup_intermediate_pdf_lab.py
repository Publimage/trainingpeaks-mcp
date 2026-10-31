"""Clean up private disposable PDF transfer note and local staging file.

Only after Intermediate README has all three correct native PDF attachments.
Lab note contains expiring signed URI, so remove it from provider once used.
"""
import asyncio,hashlib,json
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
LAB=684484
LAB_NOTE=2655001
PDF=Path("/home/ironman/.local/state/ironman-operator/intermediate-guide-v3.pdf")
FILE_SHA="7759224d295123bfdab5203dd82dfc7822228b0a3e60885a6b1003a1b4d7c938"
EXPECTED_PDF="IRONMAN_Intermediate_24W_Guida_Atleta_v3_Verificata.pdf"
async def run():
 async with TPClient() as c:
  me=await c._get_user_data()
  assert isinstance(me,dict) and me["personId"]==OWNER,"WRONG_OWNER"
  target=await c.get("/plans/v1/plans/684602")
  assert not target.is_error and target.data["title"]=="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
  assert target.data["workoutCount"]==259
  tn=await c.get("/plans/v1/plans/684602/calendarNote/2026-10-05/2027-04-01")
  assert not tn.is_error and len(tn.data)==35
  first=[n for n in tn.data if n.get("noteDate","")[:10]=="2026-10-05"]
  assert [n["id"] for n in first]==[2653899,2654983,2654984]
  ats=first[0].get("attachments",[])
  assert len(ats)==3 and {a["id"] for a in ats}=={95193,95194,95228}
  new=next(a for a in ats if a["id"]==95228)
  assert new["fileName"]==EXPECTED_PDF and new["contentLength"]==396936
  p=await c.get(f"/plans/v1/plans/{LAB}")
  assert not p.is_error and p.data["title"]=="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
  assert p.data["workoutCount"]==1 and p.data["isPublic"] is False
  async def labnotes():
   r=await c.get(f"/plans/v1/plans/{LAB}/calendarNote/2027-07-05/2027-07-12")
   assert not r.is_error and isinstance(r.data,list)
   return r.data
  before=await labnotes()
  assert len(before)==2 and {n["id"] for n in before}=={2651317,LAB_NOTE}
  anchor=next(n for n in before if n["id"]==2651317)
  transfer=next(n for n in before if n["id"]==LAB_NOTE)
  assert transfer.get("title")=="[MCP TEST] IRONMAN INTERMEDIATE V3 PDF TEMP TRANSFER"
  assert transfer.get("description","").startswith("SIGNED_READ_URI=")
  assert len(transfer.get("attachments",[]))==1 and transfer["attachments"][0]["id"]==95227
  res=await c._request("DELETE",f"/plans/v1/plans/{LAB}/calendarNote/{LAB_NOTE}",_retry_on_401=False)
  if res.is_error:
   print("LAB_CLEANUP_DELETE_UNCERTAIN_STOP",str(res.error_code));return 2
  after=await labnotes()
  assert len(after)==1 and after[0]==anchor,"LAB_NOT_RESTORED"
  again=await c.get(f"/plans/v1/plans/{LAB}")
  assert not again.is_error and again.data["workoutCount"]==1,"LAB_WORKOUT_DRIFT"
  # The final PDF lives on Drive and as native TP attachment. Local temp no longer needed.
  if PDF.exists():
   assert PDF.is_file() and PDF.stat().st_size==396936
   assert hashlib.sha256(PDF.read_bytes()).hexdigest()==FILE_SHA
   PDF.unlink()
  print("LAB_TEMP_NOTE_DELETED_AND_VERIFIED",json.dumps({
    "lab_plan_id":LAB,"remaining_notes":1,"lab_workouts":1,
    "staging_file_removed":True,
    "target_plan_id":684602,"target_pdfs":3,
    "target_new_attachment_id":95228},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(run()))
