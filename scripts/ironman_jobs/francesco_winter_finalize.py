"""Finalize Francesco Franceschini Winter Foundation athlete calendar.

Exact scope only:
- athlete 5590716, 2026-11-02..2026-12-27;
- repair planned duration on 16 exact native StructuredStrength workouts;
- keep W1-W2 Strength visible and hide W3-W8 Strength;
- copy the exact verified PDF from Winter Foundation plan START note to the
  athlete START note, with binary hash/size verification and provider readback.

Never creates workouts or notes. Never retries an ambiguous attachment POST.
"""
from __future__ import annotations
import asyncio, base64, copy, hashlib, json
import httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access, _headers, STRENGTH_API_BASE

OWNER=2116886
ATHLETE=5590716
PLAN=689369
SOURCE_NOTE=2685704
SOURCE_ATTACHMENT=105393
TARGET_NOTE=99785295
FILENAME="Guida_lettura_allenamenti_Alberto_Fazi_Endurance_TEMPLATE_v1.pdf"
PDF_SIZE=407035
PDF_SHA="7f947d35e81ea4a7fb423ccd19441f2ade5646dda025ce0bda41a2ce98fd3c1b"

EXPECTED=[
("37293975","2026-11-04","FORZA | Tecnica squat e fondamentali 50 min",50,False),
("37293980","2026-11-06","FORZA | Unilaterale e parte superiore 45 min",45,False),
("37293987","2026-11-11","FORZA | Adattamento fondamentali 55 min",55,False),
("37293988","2026-11-13","FORZA | Unilaterale controllato 50 min",50,False),
("37293991","2026-11-18","FORZA | Sviluppo tecnico 60 min",60,True),
("37294000","2026-11-20","FORZA | Glutei e controllo 50 min",50,True),
("37294008","2026-11-25","FORZA | Scarico tecnico squat 45 min",45,True),
("37294013","2026-11-27","FORZA | Scarico controllo 40 min",40,True),
("37294019","2026-12-02","FORZA | Squat sviluppato e spinta 60 min",60,True),
("37294024","2026-12-04","FORZA | Salita su rialzo e parte superiore 55 min",55,True),
("37294031","2026-12-09","FORZA | Stacco guidato e fondamentali 65 min",65,True),
("37294044","2026-12-11","FORZA | Spinta d'anca e richiamo 55 min",55,True),
("37294049","2026-12-16","FORZA | Intensità squat e panca 65 min",65,True),
("37294054","2026-12-18","FORZA | Salita su rialzo di richiamo 55 min",55,True),
("37294060","2026-12-23","FORZA | Consolidamento squat 50 min",50,True),
("37294065","2026-12-25","FORZA | Recupero e controllo 45 min",45,True),
]

def emit(**x): print(json.dumps(x,ensure_ascii=False,default=str),flush=True)
def must(v,msg):
    if not v: raise RuntimeError(msg)

def stable(w):
    # Compare prescription semantics only. Provider is allowed to recompute
    # compliance/derived fields after duration or visibility changes.
    return {
      "id": str(w.get("id") or ""),
      "workoutType": w.get("workoutType"),
      "calendarId": w.get("calendarId"),
      "title": w.get("title"),
      "prescribedDate": str(w.get("prescribedDate") or "")[:10],
      "instructions": w.get("instructions"),
      "blocks": w.get("blocks") or [],
      "snapshot": {
        "totalBlocks": (w.get("snapshot") or {}).get("totalBlocks"),
        "totalSets": (w.get("snapshot") or {}).get("totalSets"),
      },
    }

async def main():
  try:
    async with TPClient() as c:
      me=await c._get_user_data()
      must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
      c._athlete_id=ATHLETE

      # Exact athlete START note, before any write.
      nr=await c.get(f"/fitness/v1/athletes/{ATHLETE}/calendarNote/{TARGET_NOTE}")
      must(not nr.is_error and isinstance(nr.data,dict),"TARGET_NOTE_READ")
      note=nr.data
      must((note.get("id") or note.get("calendarNoteId"))==TARGET_NOTE,"TARGET_NOTE_ID")
      must((note.get("title") or "")=="START | Come usare WINTER FOUNDATION","TARGET_NOTE_TITLE")
      must(str(note.get("noteDate") or "")[:10]=="2026-11-02","TARGET_NOTE_DATE")
      old_atts=note.get("attachments") or []
      must(isinstance(old_atts,list),"TARGET_ATTACHMENTS_SHAPE")

      # Read and verify exact source PDF bytes from source plan attachment.
      sr=await c._client.request(
        "GET",c.base_url+f"/plans/v1/plans/{PLAN}/calendarNote/{SOURCE_NOTE}/attachments/{SOURCE_ATTACHMENT}",
        headers=c._get_headers(),timeout=35)
      must(sr.status_code==200,"SOURCE_ATTACHMENT_HTTP")
      sj=sr.json()
      must(isinstance(sj,dict) and sj.get("fileName")==FILENAME and sj.get("contentType")=="application/pdf","SOURCE_ATTACHMENT_META")
      b64=sj.get("data")
      must(isinstance(b64,str) and b64,"SOURCE_ATTACHMENT_DATA")
      blob=base64.b64decode(b64,validate=True)
      must(len(blob)==PDF_SIZE and blob.startswith(b"%PDF-"),"SOURCE_PDF_SIZE_OR_MAGIC")
      must(hashlib.sha256(blob).hexdigest()==PDF_SHA,"SOURCE_PDF_HASH")

      # Verify exact native Strength inventory and repair duration + visibility
      # via full-document round-trip. No delete/recreate.
      _,token,err=await _access(c)
      must(not err and token,"STRENGTH_AUTH")
      changed=[]
      async with httpx.AsyncClient(timeout=30,follow_redirects=False) as h:
        rr=await h.get(
          STRENGTH_API_BASE+f"/rx/activity/v1/workouts/calendar/{ATHLETE}/2026-11-02/2026-12-28",
          headers=_headers(token))
        must(rr.status_code==200,"STRENGTH_RANGE_HTTP")
        arr=rr.json()
        arr=arr.get("data") if isinstance(arr,dict) else arr
        must(isinstance(arr,list) and len(arr)==16,"STRENGTH_RANGE_COUNT")
        found={str(x.get("id") or x.get("workoutId")):(str(x.get("prescribedDate") or "")[:10],x.get("title")) for x in arr}
        must(set(found)=={x[0] for x in EXPECTED},"STRENGTH_ID_SET")

        for wid,dt,title,minutes,hidden in EXPECTED:
          must(found[wid]==(dt,title),f"STRENGTH_SLOT_{wid}")
          dr=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/{wid}",headers=_headers(token))
          must(dr.status_code==200,f"STRENGTH_DETAIL_{wid}")
          before=dr.json().get("data") or {}
          must(str(before.get("id"))==wid and before.get("calendarId")==ATHLETE,"STRENGTH_IDENTITY")
          must(before.get("workoutType")=="StructuredStrength","STRENGTH_TYPE")
          target_seconds=minutes*60
          if before.get("prescribedDurationInSeconds")==target_seconds and before.get("isHidden") is hidden:
            continue
          payload=copy.deepcopy(before)
          payload["prescribedDurationInSeconds"]=target_seconds
          payload["isHidden"]=hidden
          try:
            wr=await h.post(STRENGTH_API_BASE+"/rx/activity/v1/workouts/save",headers=_headers(token),json=payload)
          except httpx.RequestError:
            # Ambiguous UPSERT: reconcile exact state, never blindly retry.
            ar=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/{wid}",headers=_headers(token))
            must(ar.status_code==200,f"STRENGTH_AMBIGUOUS_READ_{wid}")
            after=ar.json().get("data") or {}
            must(after.get("prescribedDurationInSeconds")==target_seconds and after.get("isHidden") is hidden and stable(after)==stable(before),f"STRENGTH_AMBIGUOUS_{wid}")
            changed.append(wid); continue
          must(wr.status_code==200,f"STRENGTH_POST_{wid}_{wr.status_code}")
          ar=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/{wid}",headers=_headers(token))
          must(ar.status_code==200,f"STRENGTH_READBACK_{wid}")
          after=ar.json().get("data") or {}
          must(str(after.get("id"))==wid,"STRENGTH_DUPLICATE_RISK")
          must(after.get("prescribedDurationInSeconds")==target_seconds,"STRENGTH_DURATION")
          must(after.get("isHidden") is hidden,"STRENGTH_HIDDEN")
          must(stable(after)==stable(before),"STRENGTH_OTHER_DRIFT")
          changed.append(wid)

      # Attach PDF only if not already present. Use the athlete-note analogue
      # of the provider-proven plan-note attachment collection.
      nr2=await c.get(f"/fitness/v1/athletes/{ATHLETE}/calendarNote/{TARGET_NOTE}")
      must(not nr2.is_error and isinstance(nr2.data,dict),"TARGET_NOTE_REREAD")
      current_atts=nr2.data.get("attachments") or []
      matches=[a for a in current_atts if a.get("fileName")==FILENAME and int(a.get("contentLength") or -1)==PDF_SIZE]
      pdf_added=False
      if not matches:
        payload_base={"fileName":FILENAME,"contentType":"application/pdf","data":b64}
        payloads=[
          dict(payload_base,athleteId=ATHLETE,noteId=TARGET_NOTE),
          dict(payload_base,athleteId=ATHLETE,calendarNoteId=TARGET_NOTE),
          dict(payload_base),
        ]
        accepted=False
        for i,payload in enumerate(payloads,1):
          try:
            wr=await c._client.request(
              "POST",c.base_url+f"/fitness/v1/athletes/{ATHLETE}/calendarNote/{TARGET_NOTE}/attachments",
              headers=c._get_headers(),json=payload,timeout=60)
          except Exception:
            # Ambiguous POST: inspect once and stop unless attachment is proven.
            chk=await c.get(f"/fitness/v1/athletes/{ATHLETE}/calendarNote/{TARGET_NOTE}")
            at=(chk.data or {}).get("attachments") if not chk.is_error and isinstance(chk.data,dict) else None
            mm=[a for a in (at or []) if a.get("fileName")==FILENAME and int(a.get("contentLength") or -1)==PDF_SIZE]
            must(len(mm)==1,"PDF_POST_AMBIGUOUS")
            accepted=True; pdf_added=True; break
          if wr.status_code in (200,201,204):
            chk=await c.get(f"/fitness/v1/athletes/{ATHLETE}/calendarNote/{TARGET_NOTE}")
            must(not chk.is_error and isinstance(chk.data,dict),"PDF_SUCCESS_READBACK")
            at=chk.data.get("attachments") or []
            mm=[a for a in at if a.get("fileName")==FILENAME and int(a.get("contentLength") or -1)==PDF_SIZE]
            must(len(mm)==1,"PDF_SUCCESS_NOT_FOUND")
            accepted=True; pdf_added=True; break
          # Only explicit 400/404/405 validation rejection permits trying the
          # next payload shape. Any other response stops.
          if wr.status_code not in (400,404,405,422):
            raise RuntimeError(f"PDF_PROVIDER_REJECTED_{wr.status_code}")
        must(accepted,"PDF_NO_ACCEPTED_PAYLOAD")

      # Final note + PDF integrity.
      nf=await c.get(f"/fitness/v1/athletes/{ATHLETE}/calendarNote/{TARGET_NOTE}")
      must(not nf.is_error and isinstance(nf.data,dict),"FINAL_NOTE_READ")
      final_atts=nf.data.get("attachments") or []
      mm=[a for a in final_atts if a.get("fileName")==FILENAME and int(a.get("contentLength") or -1)==PDF_SIZE]
      must(len(mm)==1,"FINAL_PDF_NOT_EXACTLY_ONE")
      must((nf.data.get("title") or "")==(note.get("title") or "") and (nf.data.get("description") or "")==(note.get("description") or ""),"NOTE_CONTENT_DRIFT")

      emit(stage="FRANCESCO_WINTER_FINALIZE_PASS",athlete=ATHLETE,
           strength_native=16,strength_changed=len(changed),
           w1_w2_strength_visible=4,w3_w8_strength_hidden=12,
           pdf_note_id=TARGET_NOTE,pdf_file=FILENAME,pdf_size=PDF_SIZE,
           pdf_sha256=PDF_SHA,pdf_added=pdf_added,provider_writes=len(changed)+(1 if pdf_added else 0))
      return 0
  except Exception as exc:
    emit(stage="SAFE_STOP",reason=str(exc)[:300])
    return 2

if __name__=="__main__":
  raise SystemExit(asyncio.run(main()))
