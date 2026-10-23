"""One-shot undated B60 native Strength template, Chasing DRAFT library only."""
from __future__ import annotations
import asyncio,json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE,_catalogue,_build_prescription,_validate_blocks,_recount,_u
OWNER=2116886
SOURCE_LIB=3890637
TARGET_LIB=3894341
SOURCE_ID="330612"
TITLE="[DRAFT] CHASING | Forza B60 | Complementare full body + WarmUp"
A_TITLE="[DRAFT] CHASING | Forza A60 | Adattamento full body + WarmUp"
BASE="/rx/activity/v1/libraryContent/workoutLibrary"
B=[
 ("WarmUp","Attivazione generale 6-10' EXTRA",[(1,{"Reps":10}),(579,{"Reps":10}),(440,{"RepsPerSide":6})],"WU a corpo libero FUORI dai 60' forza"),
 ("SingleExercise","1. Weighted Step Up",[(165,{"RepsPerSide":6})],"1x6/lato, RIR5, rec 90s: gradino basso, non creare DOMS"),
 ("SingleExercise","2. Glute Bridge",[(579,{"Reps":10}),(579,{"Reps":10})],"2x10, postura neutra, rec 90s"),
 ("SingleExercise","3. Soleus Seated Calf Raise",[(520,{"RepsPerSide":10}),(520,{"RepsPerSide":10})],"2x10/lato, rec 60-90s"),
 ("SingleExercise","4. DB Row",[(516,{"Reps":8}),(516,{"Reps":8})],"2x8 upper pull, RIR4, rec 60-90s"),
 ("SingleExercise","5. Incline Push Up",[(616,{"Reps":8}),(616,{"Reps":8})],"2x8 upper push, rec 60-90s, RIR4"),
 ("SingleExercise","6. Band Face Pull",[(6,{"Reps":10}),(6,{"Reps":10})],"2x10 spalle e scapole, rec 60-75s"),
 ("SingleExercise","7. Side Plank",[(79,{"RepsPerSide":1,"Duration":20})],"1x20s per lato"),
 ("SingleExercise","8. Ipsilateral Dead Bug",[(5312,{"RepsPerSide":6})],"1x6 per lato senza fatica")
]
DETAIL=("CHASING THE SLOT Forza B60: richiamo complementare 60' con recuperi, carichi "
        "leggeri su gambe soprattutto il venerdi prima della bici lunga. WarmUp 6-10' "
        "extra, visibile e NON nel budget forza. Recuperi 60-90s, RIR4-5, no cedimento. "
        "FUELING: pasti abituali, carboidrati e proteine distribuiti, acqua secondo sete.")

def spec():
    blocks=[]
    for kind,title,moves,note in B:
        groups={}
        for eid,pres in moves:groups.setdefault(str(eid),[]).append(pres)
        blocks.append({"type":kind,"title":title,"notes":note,
                       "exercises":[{"id":k,"sets":v,"notes":note} for k,v in groups.items()]})
    assert len(blocks)==9
    assert _validate_blocks(blocks) is None
    return blocks

def ids(item):
    w=item.get("workout") or {}
    return [str(p.get("exercise",{}).get("id")) for b in (w.get("blocks") or [])[1:] for p in b.get("prescriptions") or []]

EXPECT=["165","579","520","516","616","6","79","5312"]
def native(item):
    w=item.get("workout") or {}
    b=w.get("blocks") or []
    return (item.get("libraryId")==TARGET_LIB and item.get("title")==TITLE
            and item.get("workoutLibraryItemType")=="ActivityWorkoutTemplate"
            and w.get("workoutType")=="StructuredStrength" and w.get("calendarId") is None
            and w.get("prescribedDate") is None and len(b)==9
            and b[0].get("blockType")=="WarmUp" and ids(item)==EXPECT)

def report(**k):print(json.dumps(k,ensure_ascii=False),flush=True)

async def main():
    blocks=spec()
    async with TPClient() as client:
        u=await client._get_user_data()
        q=await client.get("/exerciselibrary/v2/libraries")
        d={x.get("exerciseLibraryId"):x for x in q.data} if not q.is_error and isinstance(q.data,list) else {}
        names={SOURCE_LIB:"[MCP TEST] Integration Lab",TARGET_LIB:"CHASING THE SLOT | Forza — DRAFT NATIVE"}
        if not u or u.get("personId")!=OWNER or any(k not in d or d[k].get("libraryName")!=v or d[k].get("ownerId")!=OWNER for k,v in names.items()):
            report(stage="STOP_OWNER");return 2
        _,token,err=await _access(client)
        if err or not token:return 2
        async with httpx.AsyncClient(timeout=22,follow_redirects=False) as h:
            async def read(lib):
                z=await h.get(STRENGTH_API_BASE+BASE+"/"+str(lib),headers=_headers(token))
                if z.status_code!=200:raise ValueError("read")
                return z.json()
            try:
                ss=await read(SOURCE_LIB)
                tt=await read(TARGET_LIB)
            except (ValueError,httpx.RequestError):return 2
            source=[x for x in ss if str(x.get("id"))==SOURCE_ID]
            a=[x for x in tt if x.get("title")==A_TITLE]
            if len(source)!=1 or len(a)!=1 or len(tt)!=1 or len(source[0].get("workout",{}).get("blocks") or [])!=9:
                report(stage="STOP_PREFLIGHT",target_count=len(tt));return 3
            matches=[x for x in tt if x.get("title")==TITLE]
            if matches:
                report(stage="ALREADY",native=len(matches)==1 and native(matches[0]),count=len(tt))
                return 0 if len(matches)==1 and native(matches[0]) else 3
            # Copy one native workout from immutable LAB source. No calendar/date.
            copy={"libraryId":TARGET_LIB,"workoutLibraryItemId":int(SOURCE_ID),"title":TITLE}
            try:r=await h.post(STRENGTH_API_BASE+BASE+"/items/copy",headers=_headers(token),json=copy)
            except httpx.RequestError:
                report(stage="COPY_AMBIGUOUS",retry=False);return 4
            try:tt=await read(TARGET_LIB)
            except (httpx.RequestError,ValueError):return 4
            z=[x for x in tt if x.get("title")==TITLE]
            if r.status_code not in (200,201) or len(z)!=1 or len(tt)!=2:
                report(stage="COPY_UNVERIFIED",http=r.status_code,matches=len(z),retry=False);return 5
            old=z[0]
            workout=dict(old.get("workout") or {})
            catalogue=_catalogue()
            content=[]
            for part in blocks:
                content.append({"id":_u(),"blockType":part["type"],"title":part["title"],
                                "coachNotes":part["notes"],
                                "prescriptions":[_build_prescription(ex,catalogue) for ex in part["exercises"]]})
            workout["blocks"]=content;workout["title"]=TITLE;workout["instructions"]=DETAIL
            workout["snapshot"]={**(workout.get("snapshot") or {}),**_recount(content)}
            payload={"id":int(old["id"]),"libraryId":TARGET_LIB,"title":TITLE,
                     "workout":workout,"workoutLibraryItemType":"ActivityWorkoutTemplate"}
            try:done=await h.post(STRENGTH_API_BASE+BASE+"/save",headers=_headers(token),json=payload)
            except httpx.RequestError:
                report(stage="SAVE_AMBIGUOUS",copied_item=old["id"],retry=False);return 6
            try:tt=await read(TARGET_LIB)
            except (httpx.RequestError,ValueError):return 6
            last=[x for x in tt if str(x.get("id"))==str(old["id"])]
            valid=done.status_code==200 and len(tt)==2 and len(last)==1 and native(last[0])
            report(stage="READBACK",item_id=old["id"],http=done.status_code,
                   target_count=len(tt),native=valid,blocks=len(last[0].get("workout",{}).get("blocks") or []) if last else None,
                   main_ids=ids(last[0]) if last else [],retry=False)
            return 0 if valid else 7
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
