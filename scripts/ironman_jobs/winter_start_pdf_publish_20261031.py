"""Publish the exact WINTER FOUNDATION START NoteTemplate+native PDF to the coach
library, then replace Cesare's un-attached START with a native note and matching PDF.
One-shot guarded job, readable checkpoints, provider readback, no blind retry.
"""
from __future__ import annotations
import asyncio,base64,hashlib,json
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=689369
PLAN_NOTE=2685704
SOURCE_FILE_ID=105393
SHA="7f947d35e81ea4a7fb423ccd19441f2ade5646dda025ce0bda41a2ce98fd3c1b"
SIZE=407035
FILENAME="Guida_lettura_allenamenti_Alberto_Fazi_Endurance_TEMPLATE_v1.pdf"
LIB=3892900
LIB_TITLE="ALBERTO FAZI ENDURANCE | Note | IT"
ATHLETE=6133559
DAY="2026-11-02"
OLD_NOTE=99784204
TITLE="START | Come usare WINTER FOUNDATION"
def out(stage,**x):print(json.dumps(dict(stage=stage,**x),ensure_ascii=False),flush=True)
def need(ok,reason):
 if not ok:raise RuntimeError(reason)
def note_id(n):return int(n.get("id") or n.get("calendarNoteId"))
def attachment_ok(n):
 return any(a.get("fileName")==FILENAME and int(a.get("contentLength") or 0)==SIZE and a.get("id") for a in n.get("attachments") or [])
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  need(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_TP_COACH_OWNER")
  plan=await c.get(f"/plans/v1/plans/{PLAN}")
  need(not plan.is_error and plan.data.get("workoutCount")==74 and plan.data.get("weekCount")==8,"SOURCE_PLAN_CHANGED")
  source=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-01-04")
  need(not source.is_error and isinstance(source.data,list),"SOURCE_NOTES_UNAVAILABLE")
  rows=[n for n in source.data if note_id(n)==PLAN_NOTE]
  need(len(rows)==1 and rows[0].get("title")==TITLE and attachment_ok(rows[0]),"SOURCE_START_OR_ATTACHMENT_CHANGED")
  original=rows[0]
  libs=await c.get("/exerciselibrary/v2/libraries")
  need(not libs.is_error and isinstance(libs.data,list),"LIBRARIES_UNAVAILABLE")
  need(any(int(v.get("exerciseLibraryId") or 0)==LIB and v.get("libraryName")==LIB_TITLE and v.get("ownerId")==OWNER for v in libs.data),"TARGET_LIBRARY_MISMATCH")
  await c._ensure_client()
  need((await c._ensure_access_token()).success,"TP_AUTH_UNAVAILABLE")
  source_res=await c._client.get(c.base_url+f"/plans/v1/plans/{PLAN}/calendarNote/{PLAN_NOTE}/attachments/{SOURCE_FILE_ID}",headers=c._get_headers(),timeout=40)
  need(source_res.status_code==200,"PDF_SOURCE_FETCH_FAILED")
  file_json=source_res.json()
  binary=base64.b64decode(file_json["data"],validate=True)
  need(len(binary)==SIZE and binary.startswith(b"%PDF-") and hashlib.sha256(binary).hexdigest()==SHA,"PDF_SOURCE_HASH_MISMATCH")
  out("SOURCE_PDF_VERIFIED",size=len(binary),sha256=SHA)
  async def lib_items():
   rr=await c.get(f"/exerciselibrary/v2/libraries/{LIB}/items")
   need(not rr.is_error and isinstance(rr.data,list),"LIB_ITEMS_UNAVAILABLE")
   return rr.data
  items=await lib_items()
  matches=[i for i in items if i.get("itemName")==TITLE]
  need(len(matches)<=1,"AMBIGUOUS_EXISTING_LIBRARY_START")
  if matches:
   item=matches[0]
   need(item.get("description")==original.get("description") and item.get("exerciseLibraryItemType")=="NoteTemplate" and item.get("workoutTypeId")==0,"EXISTING_LIBRARY_START_CONTENT_DRIFT")
   itemid=int(item["exerciseLibraryItemId"])
   out("LIBRARY_START_ALREADY_EXISTS",item_id=itemid)
  else:
   payload={"exerciseLibraryId":LIB,"exerciseLibraryItemType":"NoteTemplate","itemName":TITLE,"workoutTypeId":0,"description":original["description"]}
   try:
    res=await c.post(f"/exerciselibrary/v1/libraries/{LIB}/items",json=payload)
   except Exception:
    out("UNVERIFIED_LIBRARY_POST_STOP");return 2
   current=await lib_items()
   matches=[i for i in current if i.get("itemName")==TITLE]
   need(len(matches)==1,"LIBRARY_CREATE_NOT_VERIFIED")
   item=matches[0];itemid=int(item["exerciseLibraryItemId"])
   need(item.get("exerciseLibraryItemType")=="NoteTemplate" and item.get("description")==original["description"],"LIBRARY_NATIVE_TYPE_OR_BODY_MISMATCH")
   out("LIBRARY_NATIVE_START_CREATED",item_id=itemid)
  linked=str(item.get("fileAttachments") or "").strip()
  if linked:
   ids=[x.strip() for x in linked.split(",") if x.strip()]
   need(len(ids)==1,"UNEXPECTED_MULTIPLE_LIBRARY_ATTACHMENTS")
   fileid=int(ids[0])
   rr=await c._client.get(c.base_url+f"/exerciselibrary/v1/libraries/{LIB}/items/{itemid}/attachments/{fileid}",headers=c._get_headers(),timeout=40)
   need(rr.status_code==200,"EXISTING_LIBRARY_ATTACHMENT_UNREADABLE")
   other=rr.json();raw=base64.b64decode(other["data"],validate=True)
   need(len(raw)==SIZE and hashlib.sha256(raw).hexdigest()==SHA,"EXISTING_LIBRARY_PDF_WRONG")
   out("LIBRARY_PDF_ALREADY_PRESENT",item_id=itemid,attachment_id=fileid)
  else:
   body={"exerciseLibraryId":LIB,"exerciseLibraryItemId":itemid,"fileName":FILENAME,"contentType":"application/pdf","data":file_json["data"]}
   try:
    response=await c._client.post(c.base_url+f"/exerciselibrary/v1/libraries/{LIB}/items/{itemid}/attachments",headers=c._get_headers(),json=body,timeout=75)
   except Exception:
    out("UNVERIFIED_LIBRARY_ATTACHMENT_POST_STOP",item_id=itemid);return 2
   fresh=await lib_items()
   item=next((x for x in fresh if int(x.get("exerciseLibraryItemId"))==itemid),None)
   need(item and str(item.get("fileAttachments") or "").strip(),"LIBRARY_PDF_POST_NO_READBACK")
   ids=[x.strip() for x in str(item["fileAttachments"]).split(",") if x.strip()]
   need(len(ids)==1,"LIBRARY_PDF_MULTIPLE_AFTER_POST")
   fileid=int(ids[0])
   rr=await c._client.get(c.base_url+f"/exerciselibrary/v1/libraries/{LIB}/items/{itemid}/attachments/{fileid}",headers=c._get_headers(),timeout=40)
   need(rr.status_code==200,"LIBRARY_PDF_DOWNLOAD_FAILED")
   uploaded=rr.json();filebody=base64.b64decode(uploaded["data"],validate=True)
   need(len(filebody)==SIZE and hashlib.sha256(filebody).hexdigest()==SHA,"LIBRARY_PDF_HASH_MISMATCH")
   out("LIBRARY_START_WITH_PDF_VERIFIED",item_id=itemid,pdf_attachment_id=fileid,bytes=SIZE)
  # Athlete phase begins only after the library's PDF passed byte-level verification.
  endpoint=f"/fitness/v2/athletes/{ATHLETE}/calendarNote/{DAY}/{DAY}"
  async def athlete_notes():
   rr=await c.get(endpoint)
   need(not rr.is_error and isinstance(rr.data,list),"CESARE_NOTES_READ_FAILED")
   return rr.data
  before=await athlete_notes()
  old=next((x for x in before if note_id(x)==OLD_NOTE),None)
  matches=[x for x in before if x.get("title")==TITLE]
  need(len(matches) in (1,2),"CESARE_START_DUPLICATES_OR_MISSING")
  need(old is not None and old.get("description")==original["description"] and old.get("noteDate","").startswith(DAY),"CESARE_OLD_START_DRIFT")
  need(not (old.get("attachments") or []),"CESARE_OLD_START_UNEXPECTED_ATTACHMENT")
  replacement=[x for x in matches if note_id(x)!=OLD_NOTE]
  need(len(replacement)<=1,"CESARE_MULTIPLE_REPLACEMENT_STARTS")
  if replacement:
   new=replacement[0];newid=note_id(new)
   need(new.get("description")==original["description"],"PREEXISTING_REPLACEMENT_BODY_DRIFT")
   out("CESARE_REPLACEMENT_ALREADY_EXISTS",id=newid)
  else:
   payload={"athleteId":ATHLETE,"noteDate":DAY+"T00:00:00","title":TITLE,"description":original["description"]}
   try:
    response=await c.post(f"/fitness/v1/athletes/{ATHLETE}/calendarNote",json=payload)
   except Exception:
    out("CESARE_NOTE_CREATE_UNVERIFIED_STOP");return 2
   now=await athlete_notes()
   candidates=[x for x in now if x.get("title")==TITLE and note_id(x)!=OLD_NOTE]
   need(len(candidates)==1,"CESARE_REPLACEMENT_CREATE_NO_READBACK")
   new=candidates[0];newid=note_id(new)
   need(new.get("description")==original["description"],"CESARE_NEW_BODY_WRONG")
   out("CESARE_REPLACEMENT_NOTE_CREATED",note_id=newid)
  if not attachment_ok(new):
   need(not (new.get("attachments") or []),"CESARE_REPLACEMENT_HAS_OTHER_PDF")
   body={"athleteId":ATHLETE,"noteId":newid,"fileName":FILENAME,"contentType":"application/pdf","data":file_json["data"]}
   try:
    response=await c._client.post(c.base_url+f"/fitness/v1/athletes/{ATHLETE}/calendarNote/{newid}/attachments",headers=c._get_headers(),json=body,timeout=75)
   except Exception:
    out("CESARE_PDF_POST_AMBIGUOUS_STOP",note_id=newid);return 2
   now=await athlete_notes()
   new=next((x for x in now if note_id(x)==newid),None)
   need(new and attachment_ok(new),"CESARE_PDF_NOT_VERIFIED_STOP")
   out("CESARE_NEW_START_PDF_VERIFIED",note_id=newid,attachments=new["attachments"])
  else:out("CESARE_PDF_ALREADY_PRESENT",note_id=newid)
  # Safe replacement: delete the old note only after the new has the correct PDF.
  current=await athlete_notes()
  good=next((x for x in current if note_id(x)==newid),None)
  need(good and good.get("description")==original["description"] and attachment_ok(good),"PREDELETE_REPLACEMENT_NOT_VERIFIED")
  need(any(note_id(x)==OLD_NOTE for x in current),"OLD_NOTE_ABSENT_BEFORE_DELETE")
  need(len([x for x in current if x.get("title")==TITLE])==2,"PREDELETE_START_COUNT_DRIFT")
  deletion=await c.delete(f"/fitness/v1/athletes/{ATHLETE}/calendarNote/{OLD_NOTE}")
  final=await athlete_notes()
  starts=[x for x in final if x.get("title")==TITLE]
  need(len(starts)==1 and note_id(starts[0])==newid and attachment_ok(starts[0]),"CESARE_FINAL_START_MISMATCH")
  need(not any(note_id(x)==OLD_NOTE for x in final),"CESARE_OLD_START_NOT_DELETED")
  need(len(final)==len(before),"CESARE_NATIVE_NOTE_COUNT_DRIFT")
  # Source library and source plan untouched.
  lib_check=await lib_items()
  check=next((x for x in lib_check if int(x.get("exerciseLibraryItemId"))==itemid),None)
  need(check and check.get("exerciseLibraryItemType")=="NoteTemplate" and str(check.get("fileAttachments") or "").strip(),"LIBRARY_POSTFLIGHT_MISMATCH")
  out("COMPLETE_PROVIDER_VERIFIED",athlete_id=ATHLETE,date=DAY,new_start_note_id=newid,deleted_old_note_id=OLD_NOTE,library_id=LIB,library_note_template_id=itemid,library_pdf_file_id=fileid,athlete_pdf_attachment_id=starts[0]["attachments"][0]["id"],athlete_note_count=len(final),source_plan_id=PLAN,pdf_size=SIZE,pdf_sha256=SHA)
  return 0
if __name__=="__main__":
 try:
  result=asyncio.run(main())
  if result:raise SystemExit(result)
 except Exception as e:
  out("SAFE_STOP",reason=str(e)[:280]);raise
