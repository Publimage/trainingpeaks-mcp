"""Guarded one-template-at-a-time native Strength publisher to CHASING library only.
Undated native StructuredStrength, no athlete calendar, exact block and id QA.
"""
from __future__ import annotations
import json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE,_validate_blocks,_catalogue,_build_prescription,_recount,_u
from scripts.ironman_jobs.chasing_strength_specs import SPECS,WARM

OWNER=2116886
LAB=3890637
DEST=3894341
SOURCE_ID=330612
BASE="/rx/activity/v1/libraryContent/workoutLibrary"
A_TITLE="[DRAFT] CHASING | Forza A60 | Adattamento full body + WarmUp"
B_TITLE="[DRAFT] CHASING | Forza B60 | Complementare full body + WarmUp"
KNOWN={A_TITLE,B_TITLE}|{x["title"] for x in SPECS.values()}

def blocks(key):
    spec=SPECS[key]
    all_=[{"type":"WarmUp","title":"Attivazione generale 6-10' extra NON contabilizzati",
           "notes":"Corpo libero tecnico, leggero. Fuori dai minuti di forza.",
           "exercises":[{"id":eid,"sets":sets,"notes":"WarmUp senza fatica"} for eid,sets in WARM]}]
    for idx,(eid,sets,note) in enumerate(spec["ex"],1):
        all_.append({"type":"SingleExercise","title":f"{idx}. {eid}","notes":note,
                     "exercises":[{"id":eid,"sets":sets,"notes":note}]})
    assert _validate_blocks(all_) is None
    return all_

def verify(item,key):
    s=SPECS[key]; w=item.get("workout") or {}; bs=w.get("blocks") or []
    ids=[str(p.get("exercise",{}).get("id")) for b in bs[1:] for p in b.get("prescriptions") or []]
    return (item.get("libraryId")==DEST and item.get("title")==s["title"]
            and item.get("workoutLibraryItemType")=="ActivityWorkoutTemplate"
            and w.get("workoutType")=="StructuredStrength"
            and w.get("calendarId") is None and w.get("prescribedDate") is None
            and len(bs)==len(s["ex"])+1 and bs[0].get("blockType")=="WarmUp"
            and ids==[x[0] for x in s["ex"]])

def log(**x):print(json.dumps(x,ensure_ascii=False),flush=True)

async def publish(key):
    s=SPECS[key]; wanted=blocks(key)
    async with TPClient() as client:
        user=await client._get_user_data()
        libs=await client.get("/exerciselibrary/v2/libraries")
        d={x.get("exerciseLibraryId"):x for x in libs.data} if not libs.is_error and isinstance(libs.data,list) else {}
        names={LAB:"[MCP TEST] Integration Lab",DEST:"CHASING THE SLOT | Forza — DRAFT NATIVE"}
        if not user or user.get("personId")!=OWNER or any(i not in d or d[i].get("ownerId")!=OWNER or d[i].get("libraryName")!=name for i,name in names.items()):
            log(stage="STOP_OWNER",key=key);return 2
        _,token,err=await _access(client)
        if err or not token:return 2
        async with httpx.AsyncClient(timeout=22,follow_redirects=False) as h:
            async def get(lid):
                r=await h.get(STRENGTH_API_BASE+BASE+"/"+str(lid),headers=_headers(token))
                if r.status_code!=200:raise ValueError("provider get")
                data=r.json()
                return data if isinstance(data,list) else data.get("data") or []
            try:src=await get(LAB); existing=await get(DEST)
            except (ValueError,httpx.RequestError):return 2
            source=[x for x in src if str(x.get("id"))==str(SOURCE_ID)]
            if len(source)!=1 or len(source[0].get("workout",{}).get("blocks") or [])!=9:return 3
            if len(existing)!=len({x.get("title") for x in existing}) or any(x.get("title") not in KNOWN for x in existing):
                log(stage="STOP_UNRELATED",key=key);return 3
            if not any(x.get("title")==A_TITLE for x in existing) or not any(x.get("title")==B_TITLE for x in existing):
                log(stage="STOP_PREREQ",key=key);return 3
            match=[x for x in existing if x.get("title")==s["title"]]
            if match:
                ok=len(match)==1 and verify(match[0],key)
                log(stage="ALREADY",key=key,native=ok)
                return 0 if ok else 3
            cp={"libraryId":DEST,"workoutLibraryItemId":SOURCE_ID,"title":s["title"]}
            try:r=await h.post(STRENGTH_API_BASE+BASE+"/items/copy",headers=_headers(token),json=cp)
            except httpx.RequestError:
                log(stage="COPY_AMBIGUOUS",key=key,retry=False);return 4
            try:current=await get(DEST)
            except (ValueError,httpx.RequestError):return 4
            new=[x for x in current if x.get("title")==s["title"]]
            if r.status_code not in (200,201) or len(new)!=1 or len(current)!=len(existing)+1:
                log(stage="COPY_UNVERIFIED",key=key,http=r.status_code,match=len(new),retry=False);return 5
            entry=new[0]
            doc=dict(entry["workout"])
            cat=_catalogue()
            built=[{"id":_u(),"blockType":b["type"],"title":b["title"],"coachNotes":b["notes"],
                    "prescriptions":[_build_prescription(ex,cat) for ex in b["exercises"]]} for b in wanted]
            doc["blocks"]=built; doc["title"]=s["title"]
            doc["instructions"]=(f"CHASING THE SLOT | {key} | durata forza {s['minutes']}' "
              "con recuperi fra serie e cambi esercizio. WarmUp generale 6-10' "
              "extra e non conteggiato nel budget di forza. Recuperi principali "
              "120-180s, accessori 60-90s, RIR 3-5, mai cedimento o nuova "
              "pliometria. FUELING: pasti regolari, liquidi e recupero adeguati.")
            doc["snapshot"]={**(doc.get("snapshot") or {}),**_recount(built)}
            payload={"id":int(entry["id"]),"libraryId":DEST,"title":s["title"],
                     "workout":doc,"workoutLibraryItemType":"ActivityWorkoutTemplate"}
            try:saved=await h.post(STRENGTH_API_BASE+BASE+"/save",headers=_headers(token),json=payload)
            except httpx.RequestError:
                log(stage="SAVE_AMBIGUOUS",key=key,item=entry["id"],retry=False);return 6
            try:after=await get(DEST)
            except (httpx.RequestError,ValueError):return 6
            item=[x for x in after if str(x.get("id"))==str(entry["id"])]
            ok=saved.status_code==200 and len(after)==len(existing)+1 and len(item)==1 and verify(item[0],key)
            log(stage="READBACK",key=key,id=entry["id"],http=saved.status_code,native=ok,
                total=len(after),blocks=len(item[0].get("workout",{}).get("blocks") or []) if item else None,
                exercise_ids=[x[0] for x in s["ex"]],retry=False)
            return 0 if ok else 7
