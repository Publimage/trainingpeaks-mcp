"""One-shot LAB canary: verify native plan Note PUT preserves a binary PDF.

Create one temporary Note in disposable plan 684484, attach already-verified
PDF, update only description with full provider Note body, verify PDF identity,
then delete LAB Note and restore exact anchor. No athlete calendar writes.
On ambiguous provider response STOP without retrying.
"""
import asyncio,base64,hashlib,json
from pathlib import Path
from tp_mcp.client import TPClient

OWNER=2116886
LAB=684484
ANCHOR=2651317
TITLE="[MCP TEST] README BODY PDF PRESERVATION CANARY"
ORIGINAL="Disposable protected Note with binary PDF."
UPDATED=ORIGINAL+" The athlete guide must be read first."
FILENAME="[MCP TEST] LAB ONLY PDF PRESERVATION.pdf"
def make_lab_pdf():
    content=b"BT /F1 12 Tf 40 90 Td (Disposable TrainingPeaks PDF attachment canary) Tj ET"
    stream=b"<< /Length "+str(len(content)).encode()+b" >>\\nstream\\n"+content+b"\\nendstream"
    stream=stream.replace(b"\\\\n",b"\\n")
    objects=[
      b"<< /Type /Catalog /Pages 2 0 R >>",
      b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
      b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 140] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
      stream,
      b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out=b"%PDF-1.4\\n";out=out.replace(b"\\n",b"\n")
    offsets=[0]
    for i,obj in enumerate(objects,1):
      offsets.append(len(out))
      out+=f"{i} 0 obj\\n".encode().replace(b"\\n",b"\n")+obj+b"\nendobj\n"
    xref=len(out)
    out+=f"xref\\n0 {len(objects)+1}\\n".encode().replace(b"\\n",b"\n")
    out+=b"0000000000 65535 f \n"
    for pos in offsets[1:]:
      out+=f"{pos:010d} 00000 n \\n".encode().replace(b"\\n",b"\n")
    out+=f"trailer\\n<< /Size {len(objects)+1} /Root 1 0 R >>\\nstartxref\\n{xref}\\n%%EOF".encode().replace(b"\\n",b"\n")
    return out
START="2027-07-05";END="2027-07-12"

class Stop(Exception): pass
def must(cond,reason):
    if not cond:raise Stop(reason)
async def run():
 async with TPClient() as client:
  owner=await client._get_user_data()
  must(isinstance(owner,dict) and owner.get("personId")==OWNER,"WRONG_OWNER")
  p=await client.get(f"/plans/v1/plans/{LAB}")
  must(not p.is_error and isinstance(p.data,dict),"LAB_READ_ERROR")
  plan=p.data
  must(plan.get("title")=="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
       and plan.get("planId")==LAB and plan.get("workoutCount")==1
       and plan.get("weekCount")==1 and plan.get("isPublic") is False
       and plan.get("price") in (None,0),"LAB_SCOPE_DRIFT")
  async def notes():
   r=await client.get(f"/plans/v1/plans/{LAB}/calendarNote/{START}/{END}")
   must(not r.is_error and isinstance(r.data,list),"LAB_NOTES_READ_FAILED")
   return r.data
  original=await notes()
  must(len(original)==1 and original[0].get("id")==ANCHOR,"LAB_NOT_EMPTY")
  anchor=json.dumps(original[0],sort_keys=True)
  pdf=make_lab_pdf()
  must(pdf.startswith(b"%PDF-") and pdf.endswith(b"%%EOF") and len(pdf)>300,"LAB_PDF_INVALID")
  payload={"planId":LAB,"title":TITLE,"noteDate":START,
           "description":ORIGINAL,"attachments":[],"standardFormatDate":"Week 1, Monday"}
  try:
   response=await client._request("POST",f"/plans/v1/plans/{LAB}/calendarNote",
                       json=payload,_retry_on_401=False)
  except Exception as e:
   print("STOP_AMBIGUOUS_CREATE",type(e).__name__,flush=True);return 2
  if response.is_error:
   print("STOP_CREATE_REJECTED",str(response.error_code),flush=True);return 2
  now=await notes()
  new=[x for x in now if x.get("title")==TITLE and x.get("description")==ORIGINAL]
  must(len(new)==1 and len(now)==2 and json.dumps(next(x for x in now if x.get("id")==ANCHOR),sort_keys=True)==anchor,"LAB_NEW_NOTE_NOT_UNIQUE")
  nid=new[0]["id"]
  print("LAB_NEW_NOTE_CREATED",nid,flush=True)
  try:
   await client._ensure_client()
   token=await client._ensure_access_token()
   must(token.success,"TOKEN_UNAVAILABLE")
   res=await client._client.request("POST",
    f"{client.base_url}/plans/v1/plans/{LAB}/calendarNote/{nid}/attachments",
    headers=client._get_headers(),json={
      "planId":LAB,"noteId":nid,"fileName":FILENAME,
      "contentType":"application/pdf","data":base64.b64encode(pdf).decode("ascii")
    },timeout=60)
  except Exception as e:
   print("STOP_AMBIGUOUS_ATTACHMENT",type(e).__name__,flush=True);return 2
  if res.status_code not in (200,201,204):
   print("STOP_ATTACHMENT_REJECTED",res.status_code,flush=True);return 2
  now=await notes()
  tmp=next(x for x in now if x.get("id")==nid)
  before_att=tmp.get("attachments") or []
  must(len(before_att)==1 and before_att[0].get("fileName")==FILENAME
       and before_att[0].get("contentLength")==len(pdf),"LAB_PDF_ATTACHMENT_FAILED")
  # Put original provider Note object plus single changed description.
  put_payload=dict(tmp)
  put_payload["description"]=UPDATED
  put_payload["planId"]=LAB
  try:
   upd=await client._request("PUT",f"/plans/v1/plans/{LAB}/calendarNote/{nid}",
         json=put_payload,_retry_on_401=False)
  except Exception as e:
   print("STOP_AMBIGUOUS_PUT",type(e).__name__,flush=True);return 2
  if upd.is_error:
   print("STOP_PUT_REJECTED",str(upd.error_code),flush=True);return 2
  after=await notes()
  changed=next(x for x in after if x.get("id")==nid)
  must(changed.get("description")==UPDATED and changed.get("title")==TITLE
       and changed.get("noteDate")==START,"LAB_BODY_NOT_UPDATED")
  must(changed.get("attachments")==before_att,"LAB_PDF_ATTACHMENT_CHANGED")
  must(json.dumps(next(x for x in after if x.get("id")==ANCHOR),sort_keys=True)==anchor,
       "LAB_ANCHOR_CHANGED")
  print("LAB_BODY_UPDATED_ATTACHMENT_PRESERVED",nid,flush=True)
  try:
   delete=await client._request("DELETE",f"/plans/v1/plans/{LAB}/calendarNote/{nid}",
                    _retry_on_401=False)
  except Exception as e:
   print("STOP_AMBIGUOUS_DELETE",type(e).__name__,flush=True);return 2
  if delete.is_error:
   print("STOP_DELETE_REJECTED",str(delete.error_code),flush=True);return 2
  final=await notes()
  must(len(final)==1 and json.dumps(final[0],sort_keys=True)==anchor,
       "LAB_NOT_RESTORED")
  print("LAB_NOTE_PUT_WITH_PDF_CANARY_PASS",json.dumps({
    "lab":LAB,"note":nid,"binary_pdf_preserved":True,"anchor_restored":True,
    "remaining_lab_notes":1,"target_plan_untouched":684602},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(run()))
 except Stop as e:
  print("STOP_REVIEW",str(e),flush=True);raise SystemExit(2)
