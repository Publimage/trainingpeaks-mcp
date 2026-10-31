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
        # Final visibility/integrity audit after guarded finalization.
        wr=await c.get(f"/fitness/v6/athletes/{ATHLETE}/workouts/2026-11-02/2026-12-27")
        if wr.is_error or not isinstance(wr.data,list) or len(wr.data)!=58:
            emit(stage="STOP_CLASSIC_FINAL",count=len(wr.data) if isinstance(wr.data,list) else None); return 2
        visible=[x for x in wr.data if str(x.get("workoutDay") or "")[:10] <= "2026-11-15"]
        hidden=[x for x in wr.data if str(x.get("workoutDay") or "")[:10] >= "2026-11-16"]
        if len(visible)!=12 or len(hidden)!=46 or any(x.get("isHidden") is True for x in visible) or any(x.get("isHidden") is not True for x in hidden):
            emit(stage="STOP_CLASSIC_VISIBILITY",visible=len(visible),hidden=len(hidden),
                 visible_hidden=sum(1 for x in visible if x.get("isHidden") is True),
                 later_not_hidden=sum(1 for x in hidden if x.get("isHidden") is not True)); return 2
        if any(not x.get("structure") for x in wr.data):
            emit(stage="STOP_CLASSIC_STRUCTURE",missing=sum(1 for x in wr.data if not x.get("structure"))); return 2

        nn=await c.get(f"/fitness/v2/athletes/{ATHLETE}/calendarNote/2026-11-02/2026-12-27")
        if nn.is_error or not isinstance(nn.data,list) or len(nn.data)!=9:
            emit(stage="STOP_NOTES_FINAL"); return 2
        note_visible=[x for x in nn.data if str(x.get("noteDate") or "")[:10] <= "2026-11-15"]
        note_hidden=[x for x in nn.data if str(x.get("noteDate") or "")[:10] >= "2026-11-16"]
        if len(note_visible)!=3 or len(note_hidden)!=6 or any(x.get("isHidden") is True for x in note_visible) or any(x.get("isHidden") is not True for x in note_hidden):
            emit(stage="STOP_NOTE_VISIBILITY"); return 2
        sn=next((x for x in nn.data if (x.get("id") or x.get("calendarNoteId"))==TARGET_NOTE),None)
        aa=(sn or {}).get("attachments") or []
        if len([a for a in aa if a.get("fileName")=="Guida_lettura_allenamenti_Alberto_Fazi_Endurance_TEMPLATE_v1.pdf" and int(a.get("contentLength") or -1)==407035])!=1:
            emit(stage="STOP_NOTE_PDF_FINAL"); return 2

        async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
            sr=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/calendar/{ATHLETE}/2026-11-02/2026-12-28",headers=_headers(token))
            data=sr.json() if sr.status_code==200 else None
            data=data.get("data") if isinstance(data,dict) else data
            if not isinstance(data,list) or len(data)!=16:
                emit(stage="STOP_STRENGTH_FINAL_COUNT",count=len(data) if isinstance(data,list) else None); return 2
            expected_minutes={
              "37293975":50,"37293980":45,"37293987":55,"37293988":50,
              "37293991":60,"37294000":50,"37294008":45,"37294013":40,
              "37294019":60,"37294024":55,"37294031":65,"37294044":55,
              "37294049":65,"37294054":55,"37294060":50,"37294065":45,
            }
            for x in data:
                wid=str(x.get("id") or x.get("workoutId") or "")
                dd=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/{wid}",headers=_headers(token))
                z=dd.json().get("data") if dd.status_code==200 else None
                if not isinstance(z,dict) or expected_minutes.get(wid)*60!=z.get("prescribedDurationInSeconds"):
                    emit(stage="STOP_STRENGTH_FINAL_DURATION",id=wid); return 2
                should_hide=str(z.get("prescribedDate") or "")[:10] >= "2026-11-16"
                if z.get("isHidden") is not should_hide:
                    emit(stage="STOP_STRENGTH_FINAL_VISIBILITY",id=wid,expected=should_hide,actual=z.get("isHidden")); return 2

        emit(stage="FINAL_VISIBILITY_AUDIT_PASS",classic=58,classic_visible=12,classic_hidden=46,
             notes=9,notes_visible=3,notes_hidden=6,native_strength=16,
             strength_visible=4,strength_hidden=12,pdf_verified=True,writes=0)
        emit(stage="READ_ONLY_PASS",writes=0)
        return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
