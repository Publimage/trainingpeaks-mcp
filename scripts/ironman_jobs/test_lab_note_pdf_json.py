"""Guarded exact JSON upload canary on disposable native Plan note.

Known POST route only accepts JSON; lab probes identify planId+noteId+data.
Never repeat an ambiguous upload; verify readback for duplicate prevention.
"""
import asyncio,base64,hashlib,json
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
  baseline=await notes()
  must(len(baseline)==2 and {n["id"] for n in baseline}=={2651317,NOTE},"LAB_NOTES_DRIFT")
  n=next(x for x in baseline if x["id"]==NOTE)
  must(n["title"]==TITLE and not n.get("attachments"),"LAB_ALREADY_HAS_ATTACHMENTS")
  must(PDF.is_file() and PDF.stat().st_size==396936,"PDF_NOT_STAGED")
  data=PDF.read_bytes()
  must(hashlib.sha256(data).hexdigest()==SHA,"PDF_HASH_MISMATCH")
  payload={"planId":LAB,"noteId":NOTE,"fileName":FILENAME,
           "contentType":"application/pdf","data":base64.b64encode(data).decode("ascii")}
  await c._ensure_client()
  tok=await c._ensure_access_token()
  must(tok.success,"TOKEN_MISSING")
  try:
   res=await c._client.request("POST",
     f"{c.base_url}/plans/v1/plans/{LAB}/calendarNote/{NOTE}/attachments",
     headers=c._get_headers(),json=payload,timeout=60)
  except Exception as exc:
   print("JSON_POST_AMBIGUOUS",type(exc).__name__,flush=True);return 2
  print("JSON_PDF_POST_HTTP",res.status_code,"MESSAGE",res.text[:400],flush=True)
  after=await notes()
  must(len(after)==2 and {x["id"] for x in after}=={2651317,NOTE},"LAB_NOTE_COUNT_DRIFT")
  must(next(x for x in baseline if x["id"]==2651317)==next(x for x in after if x["id"]==2651317),
       "LAB_CONTROL_NOTE_CHANGED")
  n2=next(x for x in after if x["id"]==NOTE)
  attaches=n2.get("attachments",[])
  if res.status_code not in (200,201,204):
   must(not attaches,"REJECTED_BUT_ATTACHMENT_EXISTS_STOP")
   print("JSON_PDF_REJECTED_NO_PROVIDER_CHANGE",flush=True);return 3
  must(len(attaches)==1,"LAB_PDF_ATTACH_COUNT_ERROR")
  a=attaches[0]
  must(a.get("fileName")==FILENAME and a.get("contentLength")==396936
       and a.get("id") is not None,"LAB_ATTACHMENT_METADATA_ERROR")
  must(n2.get("title")==n.get("title") and n2.get("description")==n.get("description"),
       "LAB_NOTE_BODY_CHANGED")
  print("LAB_JSON_PDF_UPLOADED_VERIFIED",json.dumps({"id":a["id"],"fileName":a["fileName"],
        "size":a["contentLength"],"plan":LAB,"note":NOTE},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(main()))
 except Stop as e:print("STOP_REVIEW",str(e),flush=True);raise SystemExit(2)
