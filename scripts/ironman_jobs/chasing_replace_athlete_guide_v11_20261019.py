"""Replace only the CHASING athlete-guide PDF attachment on the START note.

Plan 685173 is already public. This job preserves plan visibility, price, note
content, all other notes/workouts and the two other guide PDFs. It first uploads
the reviewed v1.1 athlete guide, verifies it, then deletes only the exact old
v1.0 attachment id 97221 and performs a complete scoped readback.
"""
import asyncio,base64,hashlib,json
from urllib.parse import urlsplit
import httpx
from tp_mcp.client import TPClient

OWNER=2116886
PLAN=685173
NOTE=2664007
FIRST="2027-01-04"
END="2027-06-20"
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Advanced | Italiano"
NOTE_TITLE="START | Come usare Chasing the Slot"

OLD_ID=97221
OLD_NAME="CHASING_THE_SLOT_24W_Guida_Atleta_v1.0.pdf"
OLD_BYTES=138919
KEEP={
  97222:("CHASING_THE_SLOT_24W_Guida_Settimana_per_Settimana_v1.0.pdf",222837),
  97223:("CHASING_THE_SLOT_24W_Guida_Fueling_Nutrizione_v1.0.pdf",121278),
}
NEW_NAME="CHASING THE SLOT 24W — Guida Atleta v1.1.pdf"
NEW_BYTES=145361
NEW_SHA="be871aee7f899e834fc466048606001a19369be84f38fb2b3e35db10a5ff6d3c"
SOURCE_URL="https://sdmntprwestus3.oaiusercontent.com/files/00000000-97d0-81fd-8240-89b03052142a/raw?se=2026-10-19T11%3A26%3A44Z&sp=r&sv=2026-02-06&sr=b&scid=41f8922f-d7fc-554a-8fa7-7940e312fb54&skoid=5e713cdb-766b-475e-a3ca-8adb6cf99aa0&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-10-18T18%3A46%3A17Z&ske=2026-10-19T18%3A46%3A17Z&sks=b&skv=2026-02-06&sig=V2h4ustE/KzyBdr8n6Drd1U0h1GoltGlLzFg/CW%2BBuc%3D"
ALLOWED_HOSTS={"sdmntprwestus3.oaiusercontent.com"}

class Stop(Exception): pass
def must(v,msg):
    if not v: raise Stop(msg)
def nid(n): return int(n.get("id") or n.get("calendarNoteId") or n.get("noteId"))
def att_rows(n):
    return {int(a["id"]):(str(a["fileName"]),int(a["contentLength"])) for a in (n.get("attachments") or [])}

async def main():
    u=urlsplit(SOURCE_URL)
    must(u.scheme=="https" and u.hostname in ALLOWED_HOSTS and u.username is None and u.password is None,
         "SOURCE_URL_NOT_ALLOWED")
    async with httpx.AsyncClient(follow_redirects=False,timeout=45) as hc:
        rr=await hc.get(SOURCE_URL)
        must(rr.status_code==200,"SOURCE_DOWNLOAD_FAILED")
        data=rr.content
    must(len(data)==NEW_BYTES,"SOURCE_SIZE_MISMATCH")
    must(data.startswith(b"%PDF-"),"SOURCE_NOT_PDF")
    must(hashlib.sha256(data).hexdigest()==NEW_SHA,"SOURCE_HASH_MISMATCH")

    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"OWNER_WRONG")

        async def get_plan():
            r=await c.get(f"/plans/v1/plans/{PLAN}")
            must(not r.is_error and isinstance(r.data,dict),"PLAN_READ_FAILED")
            return r.data
        async def get_notes():
            r=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{FIRST}/{END}")
            must(not r.is_error and isinstance(r.data,list),"NOTES_READ_FAILED")
            return r.data

        p=await get_plan()
        must((p.get("planId"),p.get("title"),p.get("weekCount"),p.get("workoutCount"))==
             (PLAN,TITLE,24,276),"PLAN_SCOPE_CHANGED")
        must(p.get("isPublic") is True and int(p.get("price") or 0)==199,"PLAN_PUBLIC_STATE_CHANGED")

        before=await get_notes()
        must(len(before)==31 and len({nid(n) for n in before})==31,"NOTES_CHANGED")
        start=next((n for n in before if nid(n)==NOTE),None)
        must(start is not None and start.get("title")==NOTE_TITLE and start.get("noteDate","")[:10]==FIRST,
             "START_NOTE_CHANGED")
        must(len(start.get("description",""))>900,"START_BODY_CHANGED")
        expected_old={OLD_ID:(OLD_NAME,OLD_BYTES),**KEEP}
        rows=att_rows(start)
        must(rows==expected_old,"ATTACHMENTS_BASELINE_DRIFT")

        baseline_other={nid(n):n for n in before if nid(n)!=NOTE}
        baseline_start={k:v for k,v in start.items() if k!="attachments"}

        await c._ensure_client()
        tok=await c._ensure_access_token()
        must(tok.success,"AUTH_MISSING")

        # Upload new file once. Reconcile by readback if the POST is ambiguous.
        payload={"planId":PLAN,"noteId":NOTE,"fileName":NEW_NAME,
                 "contentType":"application/pdf","data":base64.b64encode(data).decode("ascii")}
        ambiguous=False
        status=None
        try:
            res=await c._client.request(
                "POST",
                f"{c.base_url}/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/attachments",
                headers=c._get_headers(),json=payload,timeout=60)
            status=res.status_code
        except Exception:
            ambiguous=True

        mid=await get_notes()
        mid_start=next(n for n in mid if nid(n)==NOTE)
        mid_atts=mid_start.get("attachments") or []
        new=[a for a in mid_atts if a.get("fileName")==NEW_NAME and int(a.get("contentLength") or 0)==NEW_BYTES]
        if len(new)!=1:
            if ambiguous:
                print("AMBIGUOUS_UPLOAD_NO_READBACK_STOP",flush=True); return 2
            print("UPLOAD_FAILED_NO_READBACK",status,flush=True); return 2
        new_id=int(new[0]["id"])
        mid_rows=att_rows(mid_start)
        must(mid_rows.get(OLD_ID)==(OLD_NAME,OLD_BYTES),"OLD_ATTACHMENT_CHANGED_BEFORE_DELETE")
        for aid,val in KEEP.items(): must(mid_rows.get(aid)==val,"KEEP_ATTACHMENT_CHANGED_"+str(aid))
        must(len(mid_rows)==4,"UPLOAD_DID_NOT_PRODUCE_EXACT_FOUR")

        # Delete exactly old v1.0 only. On ambiguous response, reconcile by readback and never blind-retry.
        del_amb=False
        try:
            dr=await c._request(
                "DELETE",
                f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/attachments/{OLD_ID}",
                _retry_on_401=False)
            del_error=dr.is_error
        except Exception:
            del_amb=True
            del_error=True

        after=await get_notes()
        must(len(after)==31 and {nid(n) for n in after}=={nid(n) for n in before},"NOTE_INVENTORY_CHANGED")
        for n in after:
            if nid(n)!=NOTE:
                must(n==baseline_other[nid(n)],"OTHER_NOTE_CHANGED_"+str(nid(n)))
        final=next(n for n in after if nid(n)==NOTE)
        must({k:v for k,v in final.items() if k!="attachments"}==baseline_start,"START_NOTE_FIELDS_CHANGED")

        final_rows=att_rows(final)
        expected_final={new_id:(NEW_NAME,NEW_BYTES),**KEEP}
        if final_rows!=expected_final:
            if del_amb:
                print("AMBIGUOUS_DELETE_UNRESOLVED_STOP",json.dumps(final_rows,ensure_ascii=False),flush=True); return 2
            must(not del_error,"DELETE_PROVIDER_REJECTED")
            raise Stop("FINAL_ATTACHMENT_SET_MISMATCH")

        pp=await get_plan()
        must((pp.get("title"),pp.get("workoutCount"),pp.get("weekCount"),pp.get("isPublic"),int(pp.get("price") or 0))==
             (TITLE,276,24,True,199),"PLAN_MODIFIED")

        print("CHASING_ATHLETE_GUIDE_V11_REPLACED_VERIFIED",json.dumps({
            "planId":PLAN,"noteId":NOTE,
            "removed":{"id":OLD_ID,"fileName":OLD_NAME,"bytes":OLD_BYTES},
            "added":{"id":new_id,"fileName":NEW_NAME,"bytes":NEW_BYTES,"sha256":NEW_SHA},
            "attachment_count":3,
            "kept":[{"id":i,"fileName":v[0],"bytes":v[1]} for i,v in sorted(KEEP.items())],
            "notes":31,"workouts":276,"public":True,"price":199,
            "other_30_notes_unchanged":True,"start_note_body_unchanged":True
        },ensure_ascii=False),flush=True)
        return 0

if __name__=="__main__":
    try: raise SystemExit(asyncio.run(main()))
    except Stop as e:
        print("STOP_REVIEW",str(e),flush=True); raise SystemExit(2)
