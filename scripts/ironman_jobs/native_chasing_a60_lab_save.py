"""LAB-only native Strength Builder A60. Edits one undated template, never a calendar."""
from __future__ import annotations
import asyncio,json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE,_validate_blocks,_catalogue,_build_prescription,_u,_recount

LIB=3890637
ITEM="330612"
OLD="[MCP TEST] CHASING native Strength Library copy canary - source330012"
TITLE="[MCP TEST] CHASING | Forza A | Base full body 60min + WarmUp"
URL="/rx/activity/v1/libraryContent/workoutLibrary"
SOURCE=[
 ("WarmUp","Attivazione corpo libero 6-10min NON conteggiati",[
   ("1",{"Reps":10}),("579",{"Reps":10}),("440",{"RepsPerSide":6})],"WU separato, non riempire le 60min forza"),
 ("SingleExercise","Goblet Squat",[("144",{"Reps":8},{"Reps":8})],"2x8 RIR4-5, rec 120-180s"),
 ("SingleExercise","Romanian Deadlift",[("154",{"Reps":8},{"Reps":8})],"2x8 RIR4-5, rec 120-180s"),
 ("SingleExercise","Split Squat",[("158",{"RepsPerSide":6})],"1x6/lato, RIR5, rec 60-90s"),
 ("SingleExercise","Calf Raise",[("553",{"Reps":10},{"Reps":10})],"2x10, rec 60-90s"),
 ("SingleExercise","Single Arm DB Row",[("151",{"RepsPerSide":8},{"RepsPerSide":8})],"2x8/lato, RIR4, rec 60-90s"),
 ("SingleExercise","Push Up",[("5366",{"Reps":8},{"Reps":8})],"2x8, RIR4, rec 60-90s"),
 ("SingleExercise","Side Plank",[("79",{"RepsPerSide":1,"Duration":25},{"RepsPerSide":1,"Duration":25})],"2x25s/lato"),
 ("SingleExercise","Ipsilateral Dead Bug",[("5312",{"RepsPerSide":6})],"1x6/lato, assetto pulito")
]
IDS=["144","154","158","553","151","5366","79","5312"]
INFO=("CHASING THE SLOT: FORZA A adattamento, 60' lavoro forza con recuperi inclusi. "
      "WarmUp generale 6-10' EXTRA, visibile ma fuori budget forza; tempo fisico totale 66-70'. "
      "Fondamentali recupero 2-3', accessori 60-90s, niente cedimento, RIR4-5. "
      "FUELING: alimentazione normale, snack se necessario, recupero tra sedute con proteine+carboidrati.")

def blocks_to_builder():
    blocks=[]
    for typ,title,exs,note in SOURCE:
        blocks.append({"type":typ,"title":title,"notes":note,
                       "exercises":[{"id":eid,"sets":list(sets),"notes":note}
                                     for eid,*sets in exs]})
    assert _validate_blocks(blocks) is None
    return blocks

def provider_blocks():
    out=[]
    cat=_catalogue()
    for block in blocks_to_builder():
        out.append({"id":_u(),"blockType":block["type"],"title":block["title"],
                    "coachNotes":block["notes"],
                    "prescriptions":[_build_prescription(ex,cat) for ex in block["exercises"]]})
    return out

def check(item):
    w=item.get("workout") or {}
    blocks=w.get("blocks") or []
    ids=[str(p.get("exercise",{}).get("id")) for block in blocks[1:] for p in block.get("prescriptions") or []]
    return (item.get("libraryId")==LIB and item.get("title")==TITLE
            and item.get("workoutLibraryItemType")=="ActivityWorkoutTemplate"
            and w.get("workoutType")=="StructuredStrength" and w.get("calendarId") is None
            and w.get("prescribedDate") is None and len(blocks)==9
            and blocks[0].get("blockType")=="WarmUp" and ids==IDS)

async def main():
    assert len(SOURCE)==9 and len(INFO)<1000
    async with TPClient() as client:
        u=await client._get_user_data()
        libs=await client.get("/exerciselibrary/v2/libraries")
        lib=next((x for x in libs.data if x.get("exerciseLibraryId")==LIB),None) if not libs.is_error and isinstance(libs.data,list) else None
        if not u or u.get("personId")!=2116886 or not lib or lib.get("libraryName")!="[MCP TEST] Integration Lab" or lib.get("ownerId")!=2116886:
            print(json.dumps({"stage":"STOP_OWNER","writes":0}));return 2
        _,token,err=await _access(client)
        if err or not token:return 2
        async with httpx.AsyncClient(timeout=24,follow_redirects=False) as h:
            async def read():
                resp=await h.get(STRENGTH_API_BASE+URL+"/"+str(LIB),headers=_headers(token))
                if resp.status_code!=200:raise ValueError("GET")
                val=resp.json()
                return val if isinstance(val,list) else val.get("data") or []
            try: items=await read()
            except (ValueError,httpx.RequestError):return 2
            if len(items)!=1 or str(items[0].get("id"))!=ITEM:return 3
            item=items[0]
            if item.get("title")==TITLE:
                print(json.dumps({"stage":"ALREADY","native":check(item),"writes":0}))
                return 0 if check(item) else 4
            if item.get("title")!=OLD:return 3
            workout=dict(item.get("workout") or {})
            if workout.get("workoutType")!="StructuredStrength" or workout.get("calendarId") is not None or workout.get("prescribedDate") is not None:return 3
            changed=provider_blocks()
            workout["blocks"]=changed
            workout["title"]=TITLE
            workout["instructions"]=INFO
            workout["snapshot"]={**(workout.get("snapshot") or {}),**_recount(changed)}
            payload={"id":int(ITEM),"libraryId":LIB,"title":TITLE,
                     "workout":workout,"workoutLibraryItemType":"ActivityWorkoutTemplate"}
            print(json.dumps({"stage":"PREFLIGHT","blocks":len(changed),"main_exercises":len(IDS),"writes":0}),flush=True)
            try:
                response=await h.post(STRENGTH_API_BASE+URL+"/save",headers=_headers(token),json=payload)
            except httpx.RequestError:
                print(json.dumps({"stage":"POST_AMBIGUOUS","retry":False}));return 5
            try: result=await read()
            except (ValueError,httpx.RequestError):
                print(json.dumps({"stage":"READ_FAILED","http":response.status_code,"retry":False}));return 5
            valid=len(result)==1 and check(result[0])
            print(json.dumps({"stage":"READBACK","http":response.status_code,"native":valid,
                              "blocks":len(result[0].get("workout",{}).get("blocks") or []) if result else 0,
                              "item":ITEM,"retry":False}),flush=True)
            return 0 if response.status_code==200 and valid else 6

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
