"""Guarded lab-only probe of native athlete calendar-note PDF attachments and NoteTemplate PDF metadata.
No real athletes/plans are modified. Independent provider readback after every write.
"""
from __future__ import annotations
import asyncio, base64, json
from tp_mcp.client import TPClient
OWNER=2116886
LAB=941614
DAY="2028-12-11"
TITLE="[MCP TEST] winter START PDF transport canary"
def log(stage,**v): print(json.dumps(dict(stage=stage,**v),ensure_ascii=False),flush=True)
def need(v,m):
 if not v: raise RuntimeError(m)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  need(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  endpoint=f"/fitness/v2/athletes/{LAB}/calendarNote/{DAY}/{DAY}"
  async def notes():
   r=await c.get(endpoint)
   need(not r.is_error and isinstance(r.data,list),"LAB_NOTE_READ_FAILED")
   return r.data
  pre=await notes()
  need(not any(n.get("title")==TITLE for n in pre),"LAB_CANARY_ALREADY_EXISTS")
  payload={"athleteId":LAB,"noteDate":DAY+"T00:00:00","title":TITLE,"description":"Ephemeral test. PDF native attachment probe."}
  res=await c.post(f"/fitness/v1/athletes/{LAB}/calendarNote",json=payload)
  post=await notes()
  candidates=[n for n in post if n.get("title")==TITLE]
  need(len(candidates)==1,"LAB_POST_AMBIGUOUS")
  n=candidates[0]; nid=int(n.get("id") or n.get("calendarNoteId"))
  log("LAB_NOTE_CREATED",id=nid)
  # Minimal, self-contained PDF fixture; it is not an athlete document.
  pdf=b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
  body={"athleteId":LAB,"noteId":nid,"fileName":"LAB-native-note-probe.pdf","contentType":"application/pdf","data":base64.b64encode(pdf).decode("ascii")}
  url=f"/fitness/v1/athletes/{LAB}/calendarNote/{nid}/attachments"
  try:
   r=await c.post(url,json=body)
   log("ATTACHMENT_POST",endpoint=url,ok=not r.is_error,error=str(r.message or "")[:150])
  except Exception as e: log("ATTACHMENT_POST_EXCEPTION",error=type(e).__name__)
  after=await notes(); matches=[n for n in after if int(n.get("id") or n.get("calendarNoteId"))==nid]
  need(len(matches)==1,"LAB_NOTE_GONE")
  attached=matches[0].get("attachments") or []
  log("LAB_ATTACHMENT_READBACK",n=len(attached),files=[{"name":a.get("fileName"),"length":a.get("contentLength")} for a in attached])
  # Unconditionally clean up only the exact canary after check.
  d=await c.delete(f"/fitness/v1/athletes/{LAB}/calendarNote/{nid}")
  final=await notes()
  need(not any(n.get("title")==TITLE for n in final),"LAB_CLEANUP_UNVERIFIED")
  log("LAB_CLEANUP_OK",deleted=not d.is_error,original_notes=len(pre),final_notes=len(final),attachment_supported=any(a.get("fileName")=="LAB-native-note-probe.pdf" for a in attached))
if __name__=="__main__":
 try: asyncio.run(main())
 except Exception as e: log("SAFE_STOP",reason=str(e)[:240]);raise
