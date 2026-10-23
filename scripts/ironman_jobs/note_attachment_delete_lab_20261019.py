"""Disposable LAB canary for deleting one native Training Plan note attachment.

Creates one temporary note in lab plan 684484, attaches a tiny PDF using the
already proven JSON attachment route, deletes only that attachment by exact ID,
verifies the note body/title/date are unchanged, then deletes the temporary note
and confirms the lab returned to its original state. No athlete calendar writes.
"""
import asyncio,base64,json
from tp_mcp.client import TPClient

OWNER=2116886
LAB=684484
ANCHOR=2651317
START="2027-07-05"
END="2027-07-12"
TITLE="[MCP TEST] ATTACHMENT DELETE CANARY 20261019"
DESC="Disposable note used only to verify one exact attachment DELETE route."
FILENAME="[MCP TEST] attachment-delete-canary.pdf"

class Stop(Exception): pass
def must(v,msg):
    if not v: raise Stop(msg)
def note_id(n): return int(n.get("id") or n.get("calendarNoteId") or n.get("noteId"))

def tiny_pdf():
    body=b"BT /F1 12 Tf 40 90 Td (Attachment delete route canary) Tj ET"
    stream=b"<< /Length "+str(len(body)).encode()+b" >>\nstream\n"+body+b"\nendstream"
    objects=[
      b"<< /Type /Catalog /Pages 2 0 R >>",
      b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
      b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 140] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
      stream,
      b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out=b"%PDF-1.4\n"; offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(out)); out+=f"{i} 0 obj\n".encode()+obj+b"\nendobj\n"
    xref=len(out); out+=f"xref\n0 {len(objects)+1}\n".encode()+b"0000000000 65535 f \n"
    for pos in offsets[1:]: out+=f"{pos:010d} 00000 n \n".encode()
    out+=f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out

async def main():
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        p=await c.get(f"/plans/v1/plans/{LAB}")
        must(not p.is_error and isinstance(p.data,dict),"LAB_READ_FAILED")
        must(p.data.get("planId")==LAB and p.data.get("isPublic") is False
             and p.data.get("workoutCount")==0 and p.data.get("weekCount")==1,"LAB_SCOPE_DRIFT")
        async def notes():
            r=await c.get(f"/plans/v1/plans/{LAB}/calendarNote/{START}/{END}")
            must(not r.is_error and isinstance(r.data,list),"NOTES_READ_FAILED")
            return r.data
        baseline=await notes()
        must(len(baseline)==2 and {note_id(n) for n in baseline}=={ANCHOR,2655235},"LAB_NOT_CLEAN")
        baseline_json=json.dumps(baseline,sort_keys=True,ensure_ascii=False)
        payload={"planId":LAB,"title":TITLE,"noteDate":START,"description":DESC,
                 "attachments":[],"standardFormatDate":"Week 1, Monday"}
        create=await c._request("POST",f"/plans/v1/plans/{LAB}/calendarNote",json=payload,_retry_on_401=False)
        must(not create.is_error,"CREATE_FAILED")
        now=await notes()
        tmp=[n for n in now if n.get("title")==TITLE]
        must(len(tmp)==1 and len(now)==3,"TEMP_NOTE_NOT_UNIQUE")
        nid=note_id(tmp[0])
        pdf=tiny_pdf(); must(pdf.startswith(b"%PDF-") and len(pdf)>300,"PDF_INVALID")
        await c._ensure_client(); tok=await c._ensure_access_token(); must(tok.success,"AUTH_MISSING")
        res=await c._client.request("POST",
            f"{c.base_url}/plans/v1/plans/{LAB}/calendarNote/{nid}/attachments",
            headers=c._get_headers(),json={"planId":LAB,"noteId":nid,"fileName":FILENAME,
              "contentType":"application/pdf","data":base64.b64encode(pdf).decode("ascii")},timeout=60)
        must(res.status_code in (200,201,204),"ATTACH_FAILED_"+str(res.status_code))
        with_att=await notes()
        note=next(n for n in with_att if note_id(n)==nid)
        atts=note.get("attachments") or []
        must(len(atts)==1 and atts[0].get("fileName")==FILENAME and atts[0].get("id") is not None,
             "ATTACH_READBACK_FAILED")
        aid=int(atts[0]["id"])
        delete=await c._request("DELETE",
            f"/plans/v1/plans/{LAB}/calendarNote/{nid}/attachments/{aid}",_retry_on_401=False)
        route_ok=not delete.is_error
        after_delete=await notes()
        cur=next(n for n in after_delete if note_id(n)==nid)
        if route_ok:
            must((cur.get("attachments") or [])==[],"ATTACHMENT_STILL_PRESENT")
            must(cur.get("title")==TITLE and cur.get("description")==DESC and cur.get("noteDate","")[:10]==START,
                 "NOTE_CHANGED_BY_ATTACHMENT_DELETE")
        cleanup=await c._request("DELETE",f"/plans/v1/plans/{LAB}/calendarNote/{nid}",_retry_on_401=False)
        must(not cleanup.is_error,"TEMP_NOTE_CLEANUP_FAILED")
        final=await notes()
        must(len(final)==2 and json.dumps(final,sort_keys=True,ensure_ascii=False)==baseline_json,"LAB_NOT_RESTORED")
        if not route_ok:
            print(json.dumps({"stage":"ATTACHMENT_DELETE_ROUTE_NOT_SUPPORTED","attachment_id":aid,
              "provider_writes":3,"lab_restored":True},ensure_ascii=False),flush=True)
            return 2
        print(json.dumps({"stage":"ATTACHMENT_DELETE_ROUTE_VERIFIED","attachment_id":aid,
          "provider_writes":4,"note_preserved_after_attachment_delete":True,
          "lab_restored":True},ensure_ascii=False),flush=True)
        return 0

if __name__=="__main__":
    try: raise SystemExit(asyncio.run(main()))
    except Stop as e:
        print(json.dumps({"stage":"SAFE_STOP","reason":str(e)},ensure_ascii=False),flush=True)
        raise SystemExit(2)
