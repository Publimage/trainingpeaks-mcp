"""Publish reusable native TrainingPeaks Strength Builder library items.

Reuses the proved Peaksware-native copy/save/readback path from
chasing_strength_native_publish_common. No athlete calendar or Training Plan writes.
Manifest is stable, revisioned and reusable; no per-workout job registration.
"""
from __future__ import annotations
import asyncio
import json
import re
from pathlib import Path

import httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import (
    _access, _headers, STRENGTH_API_BASE,
    _validate_blocks, _catalogue, _build_prescription, _recount, _u,
)

OWNER = 2116886
DEST = 3891875
DEST_NAME = "ALBERTO FAZI ENDURANCE | Forza | IT"
SOURCE_ITEM = "330040"
BASE = "/rx/activity/v1/libraryContent/workoutLibrary"
MANIFEST = Path(__file__).resolve().parents[2] / "data/ironman_strength_library_manifest.json"

def output(**fields):
    print(json.dumps(fields, ensure_ascii=False), flush=True)

def spec():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not (data.get("schema") == "IRONMAN_STRENGTH_LIBRARY_MANIFEST_V1"
            and data.get("owner_id") == OWNER
            and data.get("provider_library_id") == DEST):
        raise ValueError("BAD_SOURCE_MANIFEST")
    items = data.get("items") or []
    if len(items) != 16 or data.get("unique_prescriptions") != 16:
        raise ValueError("SOURCE_COUNT")
    if sum(int(z.get("planned_duration_seconds", 0)) for z in items) != 845 * 60:
        raise ValueError("SOURCE_TIME")
    titles = [x.get("title") for x in items]
    if len(set(titles)) != 16:
        raise ValueError("DUPLICATE_TITLES")
    for t in titles:
        if not t or t.count("|") != 1 or re.search(r"WINTER|CHASING|IRONMAN|W\d\d|2026|2027", t, re.I):
            raise ValueError("NOT_REUSABLE_TITLE:" + str(t))
    return items

def _sets(ex):
    dosage = ex["reps"]
    count = int(ex["sets"])
    if not 1 <= count <= 5:
        raise ValueError("INVALID_SETS")
    timed = re.fullmatch(r"(\d+)\s*s(?:\s*per\s*lato)?", dosage)
    sided = "per lato" in dosage
    if timed:
        one = {"Duration": int(timed.group(1))}
        if sided:
            one["RepsPerSide"] = 1
    else:
        m = re.match(r"^(\d+)(?:-(\d+))?", dosage)
        if not m:
            raise ValueError("INVALID_REPS:" + dosage)
        one = {"RepsPerSide" if sided else "Reps": int(m.group(1))}
    return [dict(one) for _ in range(count)]

def blocks_for(item):
    warm = int(item["warmup_minutes"])
    fc = int(item["footcore_minutes_included"])
    blocks = [
        {"type":"WarmUp", "title":"Riscaldamento generale",
         "notes":f"{warm} min totali: mobilita dinamica caviglie, anche e torace, "
                 "attivazione e 1-2 serie di avvicinamento ai primi esercizi. "
                 "I video nativi illustrano il movimento, non sostituiscono il coaching.",
         "exercises":[
             {"id":"579", "sets":[{"Reps":8}],
              "notes":"Glute bridge leggero di attivazione, non allenante; 15-30 s per cambiare esercizio."},
             {"id":"5184", "sets":[{"Duration":30}],
              "notes":"Ankle roll e mobilita caviglie; nessun carico, 30-45 s prima del primo fondamentale."},
         ]},
    ]
    for ex in item["native_exercises"]:
        between=int(ex["rest_between_sets_seconds"])
        change=int(ex["rest_before_next_exercise_seconds"])
        note=(f"{ex['sets']} serie; {ex['reps']}; RPE {ex['rpe']} "
              f"(indicativamente RIR {max(1,9-int(ex['rpe']))}-"
              f"{max(2,10-int(ex['rpe']))}). "
              + (f"Recupero tra le serie: {between} secondi. " if int(ex["sets"]) > 1
                 else "Serie unica; recupero tra serie non applicabile. ")
              + (f"Dopo l'esercizio, prima del successivo: {change} secondi. "
                 if change else "Ultimo esercizio principale: nessuna pausa finale obbligatoria. ")
              + ("Per il movimento unilaterale completare i due lati prima del recupero. "
                 if "per lato" in ex["reps"] else "")
              + (ex.get("coach_notes") or "").strip())
        if ex.get("mapping") != "NATIVE_EXACT":
            note += (" MAPPING APPROVATO FUNZIONALE: il video nativo e Step Up; "
                     "sostituisce la pressa inclinata monopodalica solo come lavoro "
                     "unilaterale arti inferiori, non e la stessa macchina. "
                     "Non eseguire una pressa seguendo il video dello step-up.")
        blocks.append({"type":"SingleExercise", "title":ex["title"],
                       "notes":note,
                       "exercises":[{"id":str(ex["id"]), "sets":_sets(ex), "notes":note}]})
    # Short-foot and toe-yoga have no exact native TP library exercise. Both are
    # prescribed in the native cooldown Coach Notes, not disguised under a wrong video.
    foot_note=(f"FOOT CORE: {fc} min INCLUSI nel tempo totale. "
               "Short-foot/controllo arco 2x30s; Toe Yoga 2x6 per lato; "
               "equilibrio monopodalico 2x20-30s per lato; pause 15-30s. "
               "Solo i due seguenti movimenti sono coperti da video nativi: "
               "Toe Tap e Ankle Roll sono esercizi accessori, NON dimostrazioni "
               "equivalenti al Short Foot o al Toe Yoga. Evitare doppioni polpaccio.")
    blocks.append({"type":"CoolDown","title":"Foot core e controllo del piede",
                   "notes":foot_note,
                   "exercises":[
                       {"id":"901","sets":[{"Reps":6},{"Reps":6}],
                        "notes":foot_note+" Toe Tap: coordinazione dita; non e Toe Yoga."},
                       {"id":"5184","sets":[{"Duration":30},{"Duration":30}],
                        "notes":foot_note+" Ankle Roll: mobilita caviglia; non e Short Foot."}
                   ]})
    err = _validate_blocks(blocks)
    if err:
        raise ValueError("BUILDER_INVALID:"+err)
    return blocks

def instructions(item):
    title = item["title"]
    if title.count("|") != 1:
        raise ValueError("TITLE")
    return (f"OBIETTIVO\n{item['objective']}\n\n"
            f"DURATA PIANIFICATA\n{item['planned_duration_seconds']//60} minuti "
            "inclusivi di riscaldamento, recuperi tra le serie, pause per cambiare "
            "esercizio e foot core. La durata e indicativa, non un limite che "
            "obbliga ad accorciare i recuperi dei fondamentali.\n\n"
            "ESECUZIONE\nSeguire i blocchi native Strength Builder. RPE e "
            "reps sono nelle Coach Notes del singolo esercizio. Non andare "
            "a cedimento. Adattare il carico per conservare tecnica e RIR. "
            "Varianti con attrezzi diversi sono ammesse solo se pattern e dose "
            "restano equivalenti; le sostituzioni della pressa sono esplicite.\n\n"
            "FOOT CORE\nSeguire le istruzioni nel blocco finale. "
            "Short Foot e Toe Yoga non dispongono di video TP nativi "
            "equivalenti e NON devono essere confusi con Toe Tap.\n\n"
            "ALIMENTAZIONE\nAlimentazione ordinaria con energia sufficiente; "
            "proteine distribuite nella giornata e idratazione adeguata.")

def native_blocks(item):
    cat = _catalogue()
    result=[]
    for b in blocks_for(item):
        result.append({
            "id":_u(), "blockType":b["type"],"title":b["title"],
            "coachNotes":b["notes"],
            "prescriptions":[_build_prescription(ex,cat) for ex in b["exercises"]]
        })
    return result

def semantically_correct(entry,item):
    if (entry.get("libraryId") != DEST or entry.get("title") != item["title"] or
        entry.get("workoutLibraryItemType") != "ActivityWorkoutTemplate"):
        return False
    w=entry.get("workout") or {}
    if (w.get("workoutType") != "StructuredStrength" or
        w.get("calendarId") is not None or w.get("prescribedDate") is not None or
        w.get("prescribedDurationInSeconds") != int(item["planned_duration_seconds"])):
        return False
    got=w.get("blocks") or []
    expected=blocks_for(item)
    if len(got)!=len(expected):
        return False
    for b,ex in zip(got,expected):
        if b.get("blockType")!=ex["type"] or len(b.get("prescriptions") or [])!=len(ex["exercises"]):
            return False
        for p,want in zip(b["prescriptions"],ex["exercises"]):
            if str((p.get("exercise") or {}).get("id")) != str(want["id"]):
                return False
            if len(p.get("sets") or []) != len(want["sets"]):
                return False
            if p.get("coachNotes") != want["notes"]:
                return False
            for set_actual,set_want in zip(p["sets"],want["sets"]):
                found={v.get("parameter"):str(v.get("prescribedValue"))
                       for v in set_actual.get("parameterValues") or []}
                if found!={k:str(v) for k,v in set_want.items()}:
                    return False
    return bool(w.get("instructions") == instructions(item))

def library_identity(user,libs):
    if not user or user.get("personId") != OWNER:
        return False
    if libs.is_error or not isinstance(libs.data,list):
        return False
    match=[x for x in libs.data if x.get("exerciseLibraryId") == DEST]
    return len(match)==1 and match[0].get("libraryName")==DEST_NAME and match[0].get("ownerId")==OWNER

async def main():
    try:
        items=spec()
        for item in items:
            blocks_for(item)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        output(stage="STOP_SOURCE_QA",reason=str(exc)[:180],writes=0)
        return 2
    output(stage="SOURCE_PREFLIGHT",prescriptions=len(items),
           expected_minutes=sum(x["planned_duration_seconds"] for x in items)//60,
           native_strength_only=True,writes=0)
    async with TPClient() as client:
        user=await client._get_user_data()
        libs=await client.get("/exerciselibrary/v2/libraries")
        if not library_identity(user,libs):
            output(stage="STOP_OWNER_OR_LIBRARY",writes=0)
            return 3
        _,token,err=await _access(client)
        if err or not token:
            output(stage="STOP_AUTH",writes=0)
            return 3
        async with httpx.AsyncClient(timeout=22,follow_redirects=False) as http:
            async def read():
                response=await http.get(STRENGTH_API_BASE+BASE+"/"+str(DEST),
                                        headers=_headers(token))
                if response.status_code!=200:
                    raise ValueError("GET_NATIVE_LIBRARY_HTTP_"+str(response.status_code))
                data=response.json()
                val=data if isinstance(data,list) else data.get("data") or []
                if not isinstance(val,list):
                    raise ValueError("INVALID_NATIVE_RESPONSE")
                return val
            try:
                existing=await read()
            except (httpx.RequestError,ValueError) as exc:
                output(stage="STOP_NATIVE_READ",reason=str(exc)[:120],writes=0)
                return 3
            if (len({str(x.get("id")) for x in existing})!=len(existing) or
                len({x.get("title") for x in existing})!=len(existing)):
                output(stage="STOP_EXISTING_DUPLICATES",writes=0)
                return 3
            sources=[x for x in existing if str(x.get("id"))==SOURCE_ITEM and
                     x.get("workoutLibraryItemType")=="ActivityWorkoutTemplate" and
                     (x.get("workout") or {}).get("workoutType")=="StructuredStrength"]
            if len(sources)!=1 or len(existing)<19:
                output(stage="STOP_NO_VERIFIED_NATIVE_SOURCE",library_count=len(existing),writes=0)
                return 3
            verified=0
            attempted=0
            for idx,item in enumerate(items,1):
                title=item["title"]
                matched=[x for x in existing if x.get("title")==title]
                if matched:
                    if len(matched)!=1 or not semantically_correct(matched[0],item):
                        output(stage="STOP_MISMATCH_EXISTING",title=title,position=idx,
                               provider_writes=attempted)
                        return 4
                    verified+=1
                    continue
                # Copy a native source template using the previously proven official
                # provider library copy route. Same destination library; copy title is
                # already the permanent reuse-safe final title.
                copy_payload={"libraryId":DEST,"workoutLibraryItemId":int(SOURCE_ITEM),
                              "title":title}
                try:
                    response=await http.post(STRENGTH_API_BASE+BASE+"/items/copy",
                                              headers=_headers(token),json=copy_payload)
                except httpx.RequestError:
                    output(stage="STOP_COPY_UNCERTAIN",title=title,
                           retry=False,provider_writes=attempted)
                    return 5
                attempted+=1
                try:
                    after_copy=await read()
                except (ValueError,httpx.RequestError):
                    output(stage="STOP_COPY_READBACK_UNAVAILABLE",title=title,
                           retry=False,provider_writes=attempted)
                    return 5
                new=[x for x in after_copy if x.get("title")==title]
                if response.status_code not in (200,201) or len(new)!=1 or len(after_copy)!=len(existing)+1:
                    output(stage="STOP_COPY_UNVERIFIED",http=response.status_code,title=title,
                           match_count=len(new),retry=False,provider_writes=attempted)
                    return 5
                entry=new[0]
                doc=dict(entry.get("workout") or {})
                if doc.get("workoutType")!="StructuredStrength" or doc.get("calendarId") is not None or doc.get("prescribedDate") is not None:
                    output(stage="STOP_COPY_WRONG_KIND",title=title,retry=False,provider_writes=attempted)
                    return 5
                new_blocks=native_blocks(item)
                doc["blocks"]=new_blocks
                doc["title"]=title
                doc["instructions"]=instructions(item)
                doc["prescribedDurationInSeconds"]=int(item["planned_duration_seconds"])
                doc["snapshot"]={**(doc.get("snapshot") or {}),**_recount(new_blocks)}
                save_payload={"id":int(entry["id"]),"libraryId":DEST,"title":title,
                              "workout":doc,"workoutLibraryItemType":"ActivityWorkoutTemplate"}
                try:
                    saved=await http.post(STRENGTH_API_BASE+BASE+"/save",
                                          headers=_headers(token),json=save_payload)
                except httpx.RequestError:
                    output(stage="STOP_SAVE_UNCERTAIN",title=title,
                           item_id=entry["id"],retry=False,provider_writes=attempted)
                    return 6
                attempted+=1
                try:
                    current=await read()
                except (ValueError,httpx.RequestError):
                    output(stage="STOP_SAVE_READBACK_UNAVAILABLE",title=title,
                           retry=False,provider_writes=attempted)
                    return 6
                result=[x for x in current if x.get("title")==title]
                if (saved.status_code!=200 or len(result)!=1 or
                    len(current)!=len(existing)+1 or
                    not semantically_correct(result[0],item)):
                    output(stage="STOP_SAVE_QA",title=title,position=idx,
                           item_id=entry["id"],http=saved.status_code,
                           duration=result[0].get("workout",{}).get("prescribedDurationInSeconds") if result else None,
                           retry=False,provider_writes=attempted)
                    return 7
                existing=current
                verified+=1
                output(stage="ITEM_VERIFIED",position=idx,provider_item_id=entry["id"],
                       title=title,minutes=item["planned_duration_seconds"]//60,
                       native_blocks=len(new_blocks),provider_writes=attempted)
            if verified!=len(items):
                output(stage="STOP_INCOMPLETE",verified=verified,writes=attempted)
                return 7
            output(stage="NATIVE_STRENGTH_LIBRARY_ALL_VERIFIED",verified=verified,
                   total_native=len(existing),native_strength_only=True,
                   total_minutes=sum(x["planned_duration_seconds"] for x in items)//60,
                   athlete_calendar_writes=0,plan_writes=0,provider_writes=attempted)
            return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
