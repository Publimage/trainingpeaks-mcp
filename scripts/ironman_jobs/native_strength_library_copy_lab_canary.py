"""Guarded one-shot native Strength template copy, directly LIBRARY to LAB LIBRARY.

Uses the TrainingPeaks UI observed /rx/activity/v1/LibraryContent/workoutLibrary/items/copy
endpoint. NEVER creates a dated workout or touches an athlete/Training Plan.
Source: preexisting native Strength template 330012 (READ ONLY) in 3891875.
Target: private [MCP TEST] Integration Lab 3890637 only.
Fail closed, independent GET readback, absolutely no POST retry on ambiguity.
"""
from __future__ import annotations
import asyncio,json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE

OWNER=2116886
SOURCE_LIB=3891875
LAB_LIB=3890637
SOURCE_ID="330012"
TITLE="[MCP TEST] CHASING native Strength Library copy canary - source330012"
READ_BASE="/rx/activity/v1/libraryContent/workoutLibrary"
COPY_PATH="/rx/activity/v1/LibraryContent/workoutLibrary/items/copy"

def copy_payload()->dict:
    return {"libraryId":LAB_LIB,"workoutLibraryItemId":int(SOURCE_ID),"title":TITLE}

def natives(raw)->list[dict]:
    data=raw.get("data") if isinstance(raw,dict) else raw
    return [x for x in data if isinstance(x,dict)] if isinstance(data,list) else []

def is_native(item:dict,source:dict)->bool:
    w=item.get("workout") if isinstance(item,dict) else None
    src=source.get("workout") if isinstance(source,dict) else None
    if not isinstance(w,dict) or not isinstance(src,dict):return False
    bs=w.get("blocks") or []
    source_bs=src.get("blocks") or []
    if not isinstance(bs,list) or not isinstance(source_bs,list):return False
    return (item.get("libraryId")==LAB_LIB and item.get("title")==TITLE
            and item.get("workoutLibraryItemType")=="ActivityWorkoutTemplate"
            and w.get("workoutType")=="StructuredStrength"
            and len(bs)==len(source_bs)==6
            and [len(b.get("prescriptions") or []) for b in bs]
              == [len(b.get("prescriptions") or []) for b in source_bs])

def report(**fields):
    print(json.dumps(fields,ensure_ascii=False),flush=True)

async def main()->int:
    async with TPClient() as client:
        user=await client._get_user_data()
        if not isinstance(user,dict) or user.get("personId")!=OWNER:
            report(stage="STOP_OWNER",writes=0);return 2
        libs=await client.get("/exerciselibrary/v2/libraries")
        byid={x.get("exerciseLibraryId"):x for x in libs.data} if not libs.is_error and isinstance(libs.data,list) else {}
        if any(not byid.get(k) or byid[k].get("libraryName")!=v or byid[k].get("ownerId")!=OWNER
               for k,v in ((SOURCE_LIB,"ALBERTO FAZI ENDURANCE | Forza | IT"),(LAB_LIB,"[MCP TEST] Integration Lab"))):
            report(stage="STOP_LIBRARY",writes=0);return 2
        _,token,error=await _access(client)
        if error or not token:
            report(stage="STOP_AUTH",writes=0);return 2
        async with httpx.AsyncClient(timeout=25,follow_redirects=False) as http:
            async def read(lib:int):
                rr=await http.get(STRENGTH_API_BASE+f"{READ_BASE}/{lib}",headers=_headers(token))
                if rr.status_code!=200:raise RuntimeError("native library GET unavailable")
                return natives(rr.json())
            try:
                source=await read(SOURCE_LIB)
                before=await read(LAB_LIB)
            except (httpx.RequestError,RuntimeError,ValueError):
                report(stage="STOP_READ",writes=0);return 2
            found=[x for x in source if str(x.get("id"))==SOURCE_ID]
            if len(found)!=1 or found[0].get("workoutLibraryItemType")!="ActivityWorkoutTemplate":
                report(stage="STOP_SOURCE",writes=0);return 3
            if not isinstance(found[0].get("workout"),dict) or found[0]["workout"].get("workoutType")!="StructuredStrength":
                report(stage="STOP_SOURCE_TYPE",writes=0);return 3
            previous=[x for x in before if x.get("title")==TITLE]
            if previous:
                report(stage="ALREADY_PRESENT",count=len(previous),native=len(previous)==1 and is_native(previous[0],found[0]),writes=0)
                return 0 if len(previous)==1 and is_native(previous[0],found[0]) else 3
            if before:
                report(stage="STOP_LAB_NOT_EMPTY",count=len(before),writes=0);return 3
            report(stage="PREFLIGHT",source_lib=SOURCE_LIB,lab_lib=LAB_LIB,source_blocks=6,
                   existing_native_lab=0,writes=0)
            # This is a NEW, verified UI route. ONE POST ONLY. No blind retries.
            try:
                rr=await http.post(STRENGTH_API_BASE+COPY_PATH,json=copy_payload(),headers=_headers(token))
            except (httpx.RequestError,ValueError):
                report(stage="AMBIGUOUS_POST",retry=False);return 4
            status=rr.status_code
            try:
                data=rr.json()
            except ValueError:
                data={}
            try:
                after=await read(LAB_LIB)
            except (httpx.RequestError,RuntimeError,ValueError):
                report(stage="POST_NO_READBACK",http=status,retry=False);return 5
            item=[x for x in after if x.get("title")==TITLE]
            valid=len(item)==1 and is_native(item[0],found[0]) and len(after)==len(before)+1
            report(stage="READBACK",http=status,added=len(after)-len(before),matches=len(item),
                   native=valid,provider_type=item[0].get("workoutLibraryItemType") if item else None,
                   blocks=len(item[0].get("workout",{}).get("blocks") or []) if item else None,
                   item_id=item[0].get("id") if item else None,
                   response_keys=sorted(data.keys()) if isinstance(data,dict) else [],
                   retry=False)
            return 0 if status in (200,201) and valid else 6

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
