"""LAB only: test copying exact Winter START PDF into native NoteTemplate library entry.
Guarded creation in disposable coach library 3924002; no athlete and no main-plan writes.
"""
from __future__ import annotations
import asyncio,base64,hashlib,json
from tp_mcp.client import TPClient
OWNER=2116886
LAB_LIB=3924002
LAB_NAME="[MCP TEST] WINTER START PDF LAB 2026-10-31"
PLAN=689369
NOTE=2685704
ATT=105393
SIZE=407035
SHA="7f947d35e81ea4a7fb423ccd19441f2ade5646dda025ce0bda41a2ce98fd3c1b"
TITLE="[MCP TEST] WINTER SOURCE START WITH PDF"
def out(stage,**kw):print(json.dumps({"stage":stage,**kw},ensure_ascii=False),flush=True)
def need(v,msg):
 if not v:raise RuntimeError(msg)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  need(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  libs=await c.get("/exerciselibrary/v2/libraries")
  need(not libs.is_error and isinstance(libs.data,list),"LIBS_FAIL")
  need(any(x.get("exerciseLibraryId")==LAB_LIB and x.get("libraryName")==LAB_NAME and x.get("ownerId")==OWNER for x in libs.data),"LAB_LIBRARY_GUARD")
  r=await c.get(f"/plans/v1/plans/{PLAN}")
  need(not r.is_error and r.data.get("workoutCount")==74,"PLAN_GUARD")
  notes=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-01-04")
  need(not notes.is_error,"NOTES_READ_FAIL")
  src=next((x for x in notes.data if int(x.get("id") or x.get("calendarNoteId"))==NOTE),None)
  need(src and src.get("title")=="START | Come usare WINTER FOUNDATION","SOURCE_GUARD")
  need(any(int(a.get("id"))==ATT and int(a.get("contentLength"))==SIZE for a in src.get("attachments") or []),"ATTACHMENT_SOURCE_GUARD")
  await c._ensure_client()
  need((await c._ensure_access_token()).success,"TOKEN_FAIL")
  res=await c._client.get(c.base_url+f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/attachments/{ATT}",headers=c._get_headers(),timeout=40)
  need(res.status_code==200,"SOURCE_GET_BAD")
  meta=res.json()
  pdf=base64.b64decode(meta["data"],validate=True)
  need(pdf.startswith(b"%PDF-") and len(pdf)==SIZE and hashlib.sha256(pdf).hexdigest()==SHA,"SOURCE_PDF_HASH_MISMATCH")
  out("SOURCE_EXACT_PDF_VERIFIED",size=len(pdf),sha256=SHA)
  async def items():
   rr=await c.get(f"/exerciselibrary/v2/libraries/{LAB_LIB}/items")
   need(not rr.is_error and isinstance(rr.data,list),"ITEMS_READ_FAIL")
   return rr.data
  old=await items()
  need(not old,"LAB_NOT_EMPTY")
  payload={"exerciseLibraryId":LAB_LIB,"exerciseLibraryItemType":"NoteTemplate","itemName":TITLE,"workoutTypeId":0,"description":src["description"]}
  resp=await c.post(f"/exerciselibrary/v1/libraries/{LAB_LIB}/items",json=payload)
  current=await items()
  match=[x for x in current if x.get("itemName")==TITLE]
  need(len(match)==1,"CANARY_CREATE_UNVERIFIED")
  i=match[0];iid=int(i.get("exerciseLibraryItemId"))
  need(i.get("exerciseLibraryItemType")=="NoteTemplate" and i.get("workoutTypeId")==0,"NATIVE_NOTE_TEMPLATE_TYPE_FAIL")
  out("LAB_NATIVE_TEMPLATE_VERIFIED",item_id=iid,type=i.get("exerciseLibraryItemType"))
  body={"fileName":meta.get("fileName") or "Guida_lettura_allenamenti_Alberto_Fazi_Endurance_TEMPLATE_v1.pdf","contentType":"application/pdf","data":meta["data"],"exerciseLibraryId":LAB_LIB,"exerciseLibraryItemId":iid}
  # Probe exact provider's library-item attachment endpoints with explicit status; never repeat after 2xx.
  paths=[
   f"/exerciselibrary/v1/libraries/{LAB_LIB}/items/{iid}/attachments",
   f"/exerciselibrary/v2/libraries/{LAB_LIB}/items/{iid}/attachments",
   f"/exerciselibrary/v1/libraries/{LAB_LIB}/items/{iid}/attachment",
   f"/exerciselibrary/v1/libraries/{LAB_LIB}/items/{iid}/fileAttachments",
  ]
  for path in paths:
   status=None
   try:
    response=await c._client.post(c.base_url+path,headers=c._get_headers(),json=body,timeout=65)
    status=response.status_code
   except Exception as e:
    out("POST_UNKNOWN_DO_NOT_RETRY",route=path,exc=type(e).__name__)
    break
   allnow=await items()
   record=next(x for x in allnow if int(x.get("exerciseLibraryItemId"))==iid)
   ref=record.get("fileAttachments")
   out("LAB_UPLOAD_PROBE",route=path,status=status,attachment_ref=ref)
   if status>=200 and status<300:break
   if status not in (400,404,405,415,422):break
  final=await items()
  row=next(x for x in final if x.get("itemName")==TITLE)
  out("LAB_FINAL",item_id=iid,attachment_ref=row.get("fileAttachments"),other_items=len(final)-1,athlete_writes=0)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:out("SAFE_STOP",reason=str(e)[:280]);raise
