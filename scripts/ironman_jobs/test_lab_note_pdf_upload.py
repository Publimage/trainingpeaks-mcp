"""Guarded one-time multipart PDF attachment canary: disposable plan note only.

Do not retry ambiguous POSTs. Verify exact PDF sha256 and source TP Note plan
before upload; after POST, read note again and confirm one attached PDF.
"""
import asyncio,hashlib,json
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
LAB=684484
NOTE=2655001
TITLE="[MCP TEST] IRONMAN INTERMEDIATE V3 PDF TEMP TRANSFER"
PDF=Path("/home/ironman/.local/state/ironman-operator/intermediate-guide-v3.pdf")
FILENAME="IRONMAN_Intermediate_24W_Guida_Atleta_v3_Verificata.pdf"
SHA="7759224d295123bfdab5203dd82dfc7822228b0a3e60885a6b1003a1b4d7c938"
class Stop(Exception):pass
def must(ok,msg):
 if not ok:raise Stop(msg)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  p=await c.get(f"/plans/v1/plans/{LAB}")
  must(not p.is_error and p.data.get("title")=="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
     and p.data.get("workoutCount")==1 and p.data.get("isPublic") is False,"LAB_DRIFT")
  async def notes():
   r=await c.get(f"/plans/v1/plans/{LAB}/calendarNote/2027-07-05/2027-07-12")
   must(not r.is_error and isinstance(r.data,list),"NOTES_READ_FAILED")
   return r.data
  before=await notes()
  must(len(before)==2 and {n["id"] for n in before}=={2651317,NOTE},"LAB_NOTES_DRIFT")
  n=next(x for x in before if x["id"]==NOTE)
  must(n["title"]==TITLE and not n.get("attachments"),"LAB_ALREADY_HAS_ATTACHMENTS")
  must(PDF.is_file() and PDF.stat().st_size==396936,"PDF_NOT_STAGED")
  data=PDF.read_bytes()
  must(hashlib.sha256(data).hexdigest()==SHA,"PDF_HASH_MISMATCH")
  await c._ensure_client()
  token=await c._ensure_access_token()
  must(token.success,"TOKEN_MISSING")
  headers={k:v for k,v in c._get_headers().items() if k.lower()!="content-type"}
  url=f"{c.base_url}/plans/v1/plans/{LAB}/calendarNote/{NOTE}/attachments"
  try:
   res=await c._client.request("POST",url,headers=headers,
     files={"file":(FILENAME,data,"application/pdf")},timeout=55)
  except Exception as ex:
   print("POST_AMBIGUOUS_STOP",type(ex).__name__,flush=True);return 2
  print("LAB_POST_STATUS",res.status_code,"CONTENT_TYPE",res.headers.get("content-type"),flush=True)
  if res.status_code not in (200,201,204):
   # A clear explicit rejection is safe to diagnose without retry.
   print("LAB_POST_REJECTED",res.status_code, "BODY",res.text[:450],flush=True)
   return 3
  after=await notes()
  must(len(after)==2 and {x["id"] for x in after}=={2651317,NOTE},"POST_CHANGED_NOTE_IDS")
  must(next(x for x in after if x["id"]==2651317)==next(x for x in before if x["id"]==2651317),
       "LAB_ANCHOR_CHANGED")
  n2=next(x for x in after if x["id"]==NOTE)
  new=n2.get("attachments",[])
  must(len(new)==1,"UPLOAD_NOT_FOUND_OR_DUPLICATE")
  a=new[0]
  must(a.get("fileName")==FILENAME and a.get("contentLength")==len(data)
       and a.get("id") is not None,"LAB_ATTACHMENT_MISMATCH")
  print("LAB_ATTACHMENT_VERIFIED",json.dumps({"plan":LAB,"note":NOTE,"attachment_id":a.get("id"),
    "filename":a.get("fileName"),"size":a.get("contentLength"),"other_note_unchanged":True},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(main()))
 except Stop as e:
  print("STOP_REVIEW",str(e),flush=True);raise SystemExit(2)
