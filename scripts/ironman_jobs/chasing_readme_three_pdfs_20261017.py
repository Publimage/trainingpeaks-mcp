"""Attach the three approved CHASING THE SLOT guides to the W1 START/read-me note.

Exact scope: private Training Plan 685173, native calendar note 2664007 only.
Uses the proven native calendar-note attachment JSON endpoint. Sources are
short-lived OpenAI-signed file URLs; bytes, size and SHA256 are pinned.
Safe to resume after a partial/ambiguous attempt: readback precedes every POST.
No workout, note body/title, plan metadata, athlete calendar, library or delete.
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
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
NOTE_TITLE="START | Come usare Chasing the Slot"

FILES=[
 {
  "fileName":"CHASING_THE_SLOT_24W_Guida_Atleta_v1.0.pdf",
  "bytes":138919,
  "sha256":"309ff614cf5f05ba51b8c835b45c9a2ccdfe4b413df4ca028160cf94b5c15150",
  "url":"https://sdmntprpolandcentral.oaiusercontent.com/files/00000000-b4fc-820a-9c6e-e5081fb6ce7a/raw?se=2026-10-17T15%3A57%3A42Z&sp=r&sv=2026-02-06&sr=b&scid=4d03478a-b067-5129-bb91-0c1c5c5fefcd&skoid=b5d2651b-fef3-4bb0-a03b-ca59cc22929b&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-10-17T07%3A10%3A35Z&ske=2026-10-18T07%3A10%3A35Z&sks=b&skv=2026-02-06&sig=pBN5XfIJ4E/SjaD1J2p45mi617xwQgftnwHIjz8GZtY%3D"
 },
 {
  "fileName":"CHASING_THE_SLOT_24W_Guida_Settimana_per_Settimana_v1.0.pdf",
  "bytes":222837,
  "sha256":"ddec8ea8a8390d80a8bc6183b57634dde0eac07091efb42422444be45efb24cb",
  "url":"https://sdmntprdenmarkeast.oaiusercontent.com/files/00000000-7d88-8210-832c-c7cba2f7fc63/raw?se=2026-10-17T15%3A57%3A50Z&sp=r&sv=2026-02-06&sr=b&scid=2658353d-1954-5168-b8b1-0f84acfaed66&skoid=b5d2651b-fef3-4bb0-a03b-ca59cc22929b&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-10-17T08%3A08%3A37Z&ske=2026-10-18T08%3A08%3A37Z&sks=b&skv=2026-02-06&sig=A7MxW6KhHG4koEKGav29jyiLCY17WpQA%2B0bLxWx7cZw%3D"
 },
 {
  "fileName":"CHASING_THE_SLOT_24W_Guida_Fueling_Nutrizione_v1.0.pdf",
  "bytes":121278,
  "sha256":"598e39ccc5bb311a950ce4cb1c3aefa332246266c9f1c12f7a7b4117ad8d5cb0",
  "url":"https://sdmntprpolandcentral.oaiusercontent.com/files/00000000-0360-820a-ac3c-ceb8adc5c217/raw?se=2026-10-17T15%3A57%3A48Z&sp=r&sv=2026-02-06&sr=b&scid=f7946c88-71ea-5db1-a09e-2fff97b04c5d&skoid=b5d2651b-fef3-4bb0-a03b-ca59cc22929b&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-10-17T08%3A08%3A46Z&ske=2026-10-18T08%3A08%3A46Z&sks=b&skv=2026-02-06&sig=Y8B0lAdI3Q8PG5ILdnG/%2BNMjpUBzME0M6PzSr8w6bHA%3D"
 }
]
ALLOWED_HOSTS={"sdmntprpolandcentral.oaiusercontent.com","sdmntprdenmarkeast.oaiusercontent.com"}

class Stop(Exception): pass
def must(v,msg):
    if not v: raise Stop(msg)
def nid(n):
    return int(n.get("id") or n.get("calendarNoteId") or n.get("noteId"))
def sig(a):
    return (int(a.get("id")),str(a.get("fileName")),int(a.get("contentLength")))
def attach_map(n):
    return {str(a.get("fileName")): a for a in n.get("attachments",[])}

async def main():
    # Fetch and pin all bytes before any provider mutation.
    blobs={}
    async with httpx.AsyncClient(follow_redirects=False,timeout=45) as hc:
        for f in FILES:
            u=urlsplit(f["url"])
            must(u.scheme=="https" and u.hostname in ALLOWED_HOSTS and u.username is None and u.password is None,
                 "SOURCE_URL_NOT_ALLOWED")
            r=await hc.get(f["url"])
            must(r.status_code==200,"SOURCE_DOWNLOAD_FAILED_"+f["fileName"])
            data=r.content
            must(len(data)==f["bytes"],"SOURCE_SIZE_MISMATCH_"+f["fileName"])
            must(data.startswith(b"%PDF-"),"SOURCE_NOT_PDF_"+f["fileName"])
            must(hashlib.sha256(data).hexdigest()==f["sha256"],"SOURCE_HASH_MISMATCH_"+f["fileName"])
            blobs[f["fileName"]]=data

    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"OWNER_WRONG")

        async def get_plan():
            x=await c.get(f"/plans/v1/plans/{PLAN}")
            must(not x.is_error and isinstance(x.data,dict),"PLAN_READ_FAILED")
            return x.data

        async def get_notes():
            x=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{FIRST}/{END}")
            must(not x.is_error and isinstance(x.data,list),"NOTES_READ_FAILED")
            return x.data

        p=await get_plan()
        must((p.get("planId"),p.get("title"),p.get("weekCount"),p.get("workoutCount"))==
             (PLAN,TITLE,24,276),"PLAN_SCOPE_CHANGED")
        must(p.get("isPublic") is False,"PLAN_VISIBILITY_CHANGED")

        before=await get_notes()
        must(len(before)==31 and len({nid(n) for n in before})==31,"NOTES_CHANGED")
        start=next((n for n in before if nid(n)==NOTE),None)
        must(start is not None and start.get("title")==NOTE_TITLE and start.get("noteDate","")[:10]==FIRST,
             "START_NOTE_CHANGED")
        must(len(start.get("description",""))>900,"START_BODY_CHANGED")

        expected={f["fileName"]:(f["bytes"],f["sha256"]) for f in FILES}
        existing=attach_map(start)
        for name,a in existing.items():
            must(name in expected,"UNEXPECTED_EXISTING_ATTACHMENT_"+name)
            must(int(a.get("contentLength"))==expected[name][0],"EXISTING_ATTACHMENT_SIZE_DRIFT_"+name)
        must(len(existing)<=3,"TOO_MANY_ATTACHMENTS")

        baseline_other={nid(n):n for n in before if nid(n)!=NOTE}
        baseline_start={k:v for k,v in start.items() if k!="attachments"}

        await c._ensure_client()
        tok=await c._ensure_access_token()
        must(tok.success,"AUTH_MISSING")

        posted=[]
        skipped=[]
        for f in FILES:
            name=f["fileName"]
            current=await get_notes()
            cur=next(n for n in current if nid(n)==NOTE)
            amap=attach_map(cur)
            if name in amap:
                must(int(amap[name].get("contentLength"))==f["bytes"],"RESUME_SIZE_DRIFT_"+name)
                skipped.append(name)
                continue

            payload={"planId":PLAN,"noteId":NOTE,"fileName":name,
                     "contentType":"application/pdf",
                     "data":base64.b64encode(blobs[name]).decode("ascii")}
            ambiguous=False
            status=None
            try:
                res=await c._client.request("POST",
                    f"{c.base_url}/plans/v1/plans/{PLAN}/calendarNote/{NOTE}/attachments",
                    headers=c._get_headers(),json=payload,timeout=60)
                status=res.status_code
            except Exception:
                ambiguous=True

            check=await get_notes()
            chk=next(n for n in check if nid(n)==NOTE)
            got=attach_map(chk)
            if name in got and int(got[name].get("contentLength"))==f["bytes"]:
                posted.append(name)
                continue
            if ambiguous:
                print("AMBIGUOUS_POST_NO_READBACK_STOP",name,flush=True); return 2
            print("POST_FAILED_NO_READBACK",name,status,flush=True); return 2

        after=await get_notes()
        must(len(after)==31 and {nid(n) for n in after}=={nid(n) for n in before},"NOTE_INVENTORY_CHANGED")
        for n in after:
            if nid(n)!=NOTE:
                must(n==baseline_other[nid(n)],"OTHER_NOTE_CHANGED_"+str(nid(n)))
        final=next(n for n in after if nid(n)==NOTE)
        must({k:v for k,v in final.items() if k!="attachments"}==baseline_start,"START_NOTE_FIELDS_CHANGED")

        amap=attach_map(final)
        must(set(amap)==set(expected),"FINAL_ATTACHMENT_SET_MISMATCH")
        final_rows=[]
        for f in FILES:
            a=amap[f["fileName"]]
            must(int(a.get("contentLength"))==f["bytes"] and a.get("id") is not None,
                 "FINAL_ATTACHMENT_METADATA_MISMATCH_"+f["fileName"])
            final_rows.append({"id":int(a["id"]),"fileName":f["fileName"],"bytes":f["bytes"],"sha256":f["sha256"]})

        pp=await get_plan()
        must((pp.get("title"),pp.get("workoutCount"),pp.get("weekCount"),pp.get("isPublic"))==
             (TITLE,276,24,False),"TRAINING_PLAN_MODIFIED")

        print("CHASING_README_THREE_PDFS_ATTACHED_VERIFIED",json.dumps({
            "planId":PLAN,"noteId":NOTE,"noteTitle":NOTE_TITLE,
            "attachment_count":3,"attachments":final_rows,
            "posted":posted,"resumed_or_skipped":skipped,
            "workouts":276,"notes":31,
            "other_30_notes_unchanged":True,"start_note_body_unchanged":True
        },ensure_ascii=False),flush=True)
        return 0

if __name__=="__main__":
    try: raise SystemExit(asyncio.run(main()))
    except Stop as e:
        print("STOP_REVIEW",str(e),flush=True); raise SystemExit(2)
