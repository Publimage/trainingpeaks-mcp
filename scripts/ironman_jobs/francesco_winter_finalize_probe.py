"""READ-ONLY probe for Winter Foundation athlete-note attachment + native Strength fields."""
from __future__ import annotations
import asyncio, hashlib, json
import httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access, _headers, STRENGTH_API_BASE

OWNER=2116886
ATHLETE=5590716
PLAN=689369
SOURCE_NOTE=2685704
SOURCE_ATTACHMENT=105393
TARGET_NOTE=99785295
STRENGTH_ID="37293991"

def emit(**x):
    print(json.dumps(x,ensure_ascii=False,default=str),flush=True)

async def main():
    async with TPClient() as c:
        me=await c._get_user_data()
        if not isinstance(me,dict) or me.get("personId")!=OWNER:
            emit(stage="STOP_OWNER"); return 2
        c._athlete_id=ATHLETE
        target=await c.get(f"/fitness/v1/athletes/{ATHLETE}/calendarNote/{TARGET_NOTE}")
        if target.is_error or not isinstance(target.data,dict):
            emit(stage="STOP_TARGET_NOTE"); return 2
        t=target.data
        if (t.get("id") or t.get("calendarNoteId"))!=TARGET_NOTE or (t.get("title") or "")!="START | Come usare WINTER FOUNDATION":
            emit(stage="STOP_TARGET_IDENTITY",keys=sorted(t.keys())); return 2
        p=await c.get(f"/plans/v1/plans/{PLAN}")
        if p.is_error or not isinstance(p.data,dict) or p.data.get("ownerPersonId")!=OWNER:
            emit(stage="STOP_PLAN"); return 2
        notes=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-03-02")
        if notes.is_error or not isinstance(notes.data,list):
            emit(stage="STOP_SOURCE_NOTES"); return 2
        n=next((x for x in notes.data if (x.get("id") or x.get("calendarNoteId"))==SOURCE_NOTE),None)
        if not n:
            emit(stage="STOP_SOURCE_NOTE"); return 2
        atts=n.get("attachments") or []
        a=next((x for x in atts if x.get("id")==SOURCE_ATTACHMENT),None)
        if not a:
            emit(stage="STOP_SOURCE_ATTACHMENT",attachment_count=len(atts)); return 2
        emit(stage="SOURCE_ATTACHMENT_RAW",keys=sorted(a.keys()),
             safe={k:v for k,v in a.items() if k.lower() not in {"data","authorization","token"}})

        await c._ensure_client()
        candidates=[
            f"/plans/v1/plans/{PLAN}/calendarNote/{SOURCE_NOTE}/attachments/{SOURCE_ATTACHMENT}",
            f"/plans/v1/plans/{PLAN}/calendarNote/{SOURCE_NOTE}/attachment/{SOURCE_ATTACHMENT}",
            f"/plans/v1/plans/{PLAN}/calendarNote/{SOURCE_NOTE}/attachments/{SOURCE_ATTACHMENT}/download",
        ]
        for path in candidates:
            try:
                rr=await c._client.request("GET",c.base_url+path,headers=c._get_headers(),timeout=25)
                body=rr.content
                json_keys=[]
                json_safe={}
                if "application/json" in (rr.headers.get("content-type") or ""):
                    try:
                        jj=rr.json()
                        if isinstance(jj,dict):
                            json_keys=sorted(jj.keys())
                            for k,v in jj.items():
                                if k.lower() in {"data","filedata","content","base64"} and isinstance(v,str):
                                    json_safe[k+"_length"]=len(v)
                                elif k.lower() not in {"authorization","token"}:
                                    json_safe[k]=v
                    except Exception:
                        pass
                emit(stage="GET_PROBE",path=path,status=rr.status_code,
                     content_type=rr.headers.get("content-type"),length=len(body),
                     pdf=body.startswith(b"%PDF-"),
                     sha256=hashlib.sha256(body).hexdigest() if body.startswith(b"%PDF-") else None,
                     json_keys=json_keys,json_safe=json_safe)
            except Exception as ex:
                emit(stage="GET_PROBE_ERROR",path=path,kind=type(ex).__name__)

        for path in [
            f"/fitness/v1/athletes/{ATHLETE}/calendarNote/{TARGET_NOTE}/attachments",
            f"/fitness/v1/athletes/{ATHLETE}/calendarNote/{TARGET_NOTE}/attachment",
        ]:
            try:
                rr=await c._client.request("GET",c.base_url+path,headers=c._get_headers(),timeout=25)
                emit(stage="TARGET_ATTACHMENT_COLLECTION_GET",path=path,status=rr.status_code,
                     content_type=rr.headers.get("content-type"),length=len(rr.content))
            except Exception as ex:
                emit(stage="TARGET_ATTACHMENT_COLLECTION_ERROR",path=path,kind=type(ex).__name__)

        _,token,err=await _access(c)
        if err or not token:
            emit(stage="STOP_STRENGTH_AUTH"); return 2
        async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
            rr=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/{STRENGTH_ID}",headers=_headers(token))
            if rr.status_code!=200:
                emit(stage="STOP_STRENGTH_DETAIL",status=rr.status_code); return 2
            s=rr.json().get("data") or {}
            emit(stage="STRENGTH_RAW_KEYS",keys=sorted(s.keys()),
                 selected={k:s.get(k) for k in ("id","calendarId","title","prescribedDate","prescribedDurationInSeconds","isHidden","hidden","visibility") if k in s})
        emit(stage="READ_ONLY_PASS",writes=0)
        return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
