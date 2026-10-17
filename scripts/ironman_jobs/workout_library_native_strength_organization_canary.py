"""Guarded native StructuredStrength Workout Library organization E2E canary.

Uses the Activity Builder / Peaksware native routes observed in current TP UI.
Scope is exact owner, exact LAB source library and exact native item 330612.
Tests copy, native item delete, native move via save, exact move-back, then
removes the empty temporary library. No athlete/calendar/plan writes.
"""
from __future__ import annotations
import asyncio, copy, json, httpx
from typing import Any
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access, _headers, STRENGTH_API_BASE

OWNER=2116886
SOURCE_LIB=3890637
SOURCE_NAME="[MCP TEST] Integration Lab"
SOURCE_ID=330612
SOURCE_TITLE="[MCP TEST] CHASING | Forza A | Base full body 60min + WarmUp"
TEMP_NAME="[MCP TEST] Native Strength Organization Canary"
COPY_TITLE="[MCP TEST] Native Strength copy canary 330612"
READ_BASE="/rx/activity/v1/libraryContent/workoutLibrary"
COPY_PATH="/rx/activity/v1/LibraryContent/workoutLibrary/items/copy"
SAVE_PATH="/rx/activity/v1/libraryContent/workoutLibrary/save"
DELETE_ITEM="/rx/activity/v1/libraryContent/workoutLibrary/items/{item_id}"

class Stop(Exception):pass
def log(**x):print(json.dumps(x,ensure_ascii=False,sort_keys=True),flush=True)
def must(v,m):
    if not v:raise Stop(m)

def lib_id(x):
    v=x.get("exerciseLibraryId",x.get("id"))
    try:return int(v)
    except (TypeError,ValueError):return None

def native_items(raw):
    data=raw.get("data") if isinstance(raw,dict) else raw
    return [x for x in data if isinstance(x,dict)] if isinstance(data,list) else []

def native_id(x):
    try:return int(x.get("id"))
    except (TypeError,ValueError):return None

def canonical_native(x:dict[str,Any], *, ignore_library=False, ignore_id=False, ignore_title=False):
    y=copy.deepcopy(x)
    if ignore_library:y.pop("libraryId",None)
    if ignore_id:y.pop("id",None)
    if ignore_title:y.pop("title",None)
    return y

def move_payload(item:dict[str,Any],dest:int)->dict[str,Any]:
    return {
        "id":item["id"],
        "libraryId":dest,
        "title":item["title"],
        "workout":item["workout"],
        "workoutLibraryItemType":item["workoutLibraryItemType"],
    }

async def main()->int:
    async with TPClient() as client:
        me=await client._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        libs=await client.get("/exerciselibrary/v2/libraries")
        must(not libs.is_error and isinstance(libs.data,list),"LIBRARIES_READ_FAILED")
        byid={lib_id(x):x for x in libs.data if isinstance(x,dict)}
        src_lib=byid.get(SOURCE_LIB)
        must(src_lib and src_lib.get("libraryName")==SOURCE_NAME and src_lib.get("ownerId")==OWNER,
             "SOURCE_LIBRARY_DRIFT")

        _,token,error=await _access(client)
        must(not error and token,"STRENGTH_AUTH_FAILED")
        headers=_headers(token)

        async with httpx.AsyncClient(timeout=25,follow_redirects=False) as http:
            async def read_native(lib:int):
                rr=await http.get(STRENGTH_API_BASE+f"{READ_BASE}/{lib}",headers=headers)
                must(rr.status_code==200,f"NATIVE_READ_HTTP:{lib}:{rr.status_code}")
                return native_items(rr.json())

            source_items=await read_native(SOURCE_LIB)
            found=[x for x in source_items if native_id(x)==SOURCE_ID]
            must(len(found)==1,"SOURCE_NATIVE_ITEM_MISSING")
            source=found[0]
            must(source.get("title")==SOURCE_TITLE,"SOURCE_NATIVE_TITLE_DRIFT")
            must(source.get("workoutLibraryItemType")=="ActivityWorkoutTemplate","SOURCE_NATIVE_TYPE_DRIFT")
            must(isinstance(source.get("workout"),dict)
                 and source["workout"].get("workoutType")=="StructuredStrength","SOURCE_NOT_STRUCTURED_STRENGTH")
            baseline=canonical_native(source)
            block_sig=[len(b.get("prescriptions") or []) for b in source["workout"].get("blocks") or []]
            must(block_sig and sum(block_sig)>0,"SOURCE_BLOCKS_EMPTY")

            # Temp classic library is also the container for native Activity Builder items.
            existing=[x for x in libs.data if isinstance(x,dict) and x.get("libraryName")==TEMP_NAME]
            must(len(existing)<=1,"DUPLICATE_TEMP_LIBRARY")
            if existing:
                tid=lib_id(existing[0]);must(tid is not None,"TEMP_ID_MISSING")
                must(not await read_native(tid),"PARTIAL_TEMP_NATIVE_NOT_EMPTY")
                classic=await client.get(f"/exerciselibrary/v2/libraries/{tid}/items")
                must(not classic.is_error and isinstance(classic.data,list) and not classic.data,
                     "PARTIAL_TEMP_CLASSIC_NOT_EMPTY")
                log(stage="PREFLIGHT_REUSE_EMPTY_TEMP",library_id=tid,writes=0)
            else:
                try:
                    resp=await client._request(
                        "POST","/exerciselibrary/v1/libraries",
                        json={"libraryName":TEMP_NAME,"ownerId":OWNER},_retry_on_401=False)
                except Exception:
                    resp=None
                rb=await client.get("/exerciselibrary/v2/libraries")
                matches=[x for x in (rb.data if not rb.is_error and isinstance(rb.data,list) else [])
                         if isinstance(x,dict) and x.get("libraryName")==TEMP_NAME]
                if len(matches)!=1:
                    log(stage="CREATE_TEMP_NOT_VERIFIED",retry=False);return 4
                tid=lib_id(matches[0]);must(tid is not None,"TEMP_ID_MISSING")
                log(stage="CREATE_TEMP_VERIFIED",library_id=tid,writes=1)

            # Native copy canary.
            before=await read_native(tid)
            previous=[x for x in before if x.get("title")==COPY_TITLE]
            must(len(previous)<=1,"DUPLICATE_NATIVE_COPY_TITLE")
            if not previous:
                payload={"libraryId":tid,"workoutLibraryItemId":SOURCE_ID,"title":COPY_TITLE}
                try:
                    rr=await http.post(STRENGTH_API_BASE+COPY_PATH,json=payload,headers=headers)
                    status=rr.status_code
                except httpx.RequestError:
                    rr=None;status=None
                after=await read_native(tid)
                previous=[x for x in after if x.get("title")==COPY_TITLE]
                if len(previous)!=1:
                    log(stage="NATIVE_COPY_NOT_VERIFIED",http=status,retry=False);return 5
            copied=previous[0];copied_id=native_id(copied);must(copied_id is not None,"NATIVE_COPY_ID_MISSING")
            must(copied.get("workoutLibraryItemType")=="ActivityWorkoutTemplate","NATIVE_COPY_TYPE_DRIFT")
            must(copied.get("workout",{}).get("workoutType")=="StructuredStrength","NATIVE_COPY_WORKOUT_TYPE_DRIFT")
            must([len(b.get("prescriptions") or []) for b in copied.get("workout",{}).get("blocks") or []]==block_sig,
                 "NATIVE_COPY_BLOCK_DRIFT")
            log(stage="NATIVE_COPY_VERIFIED",copy_id=copied_id,library_id=tid,writes=1)

            # Delete disposable native copy via native Activity Builder route.
            try:
                rr=await http.delete(STRENGTH_API_BASE+DELETE_ITEM.format(item_id=copied_id),headers=headers)
                status=rr.status_code
            except httpx.RequestError:
                status=None
            after_delete=await read_native(tid)
            if any(native_id(x)==copied_id for x in after_delete):
                log(stage="NATIVE_DELETE_COPY_NOT_VERIFIED",http=status,retry=False);return 6
            log(stage="NATIVE_DELETE_COPY_VERIFIED",copy_id=copied_id,writes=1)

            # Native move of exact existing item to temp using save route.
            src_now=[x for x in await read_native(SOURCE_LIB) if native_id(x)==SOURCE_ID]
            dst_now=[x for x in await read_native(tid) if native_id(x)==SOURCE_ID]
            must(len(src_now)==1 and not dst_now,"PRE_MOVE_NATIVE_MEMBERSHIP_DRIFT")
            try:
                rr=await http.post(STRENGTH_API_BASE+SAVE_PATH,json=move_payload(src_now[0],tid),headers=headers)
                status=rr.status_code
            except httpx.RequestError:
                status=None
            src_after=[x for x in await read_native(SOURCE_LIB) if native_id(x)==SOURCE_ID]
            dst_after=[x for x in await read_native(tid) if native_id(x)==SOURCE_ID]
            if src_after or len(dst_after)!=1:
                log(stage="NATIVE_MOVE_OUT_NOT_VERIFIED",http=status,source=len(src_after),dest=len(dst_after),retry=False)
                return 7
            moved=dst_after[0]
            must(canonical_native(moved,ignore_library=True)==canonical_native(source,ignore_library=True),
                 "NATIVE_MOVE_OUT_CONTENT_DRIFT")
            log(stage="NATIVE_MOVE_OUT_VERIFIED",item_id=SOURCE_ID,to_library=tid,writes=1)

            # Move back, same ID and full workout.
            try:
                rr=await http.post(STRENGTH_API_BASE+SAVE_PATH,json=move_payload(moved,SOURCE_LIB),headers=headers)
                status=rr.status_code
            except httpx.RequestError:
                status=None
            restored=[x for x in await read_native(SOURCE_LIB) if native_id(x)==SOURCE_ID]
            temp_left=[x for x in await read_native(tid) if native_id(x)==SOURCE_ID]
            if len(restored)!=1 or temp_left:
                log(stage="NATIVE_MOVE_BACK_NOT_VERIFIED",http=status,retry=False);return 8
            must(canonical_native(restored[0])==baseline,"NATIVE_SOURCE_NOT_EXACTLY_RESTORED")
            log(stage="NATIVE_MOVE_BACK_VERIFIED",item_id=SOURCE_ID,writes=1)

        # Outside Strength HTTP client: temp must be empty in BOTH classic/native stores.
        classic=await client.get(f"/exerciselibrary/v2/libraries/{tid}/items")
        must(not classic.is_error and isinstance(classic.data,list) and not classic.data,"TEMP_CLASSIC_NOT_EMPTY")
        try:
            resp=await client._request("DELETE",f"/exerciselibrary/v1/libraries/{tid}",_retry_on_401=False)
        except Exception:
            resp=None
        rb=await client.get("/exerciselibrary/v2/libraries")
        if any(lib_id(x)==tid for x in (rb.data if not rb.is_error and isinstance(rb.data,list) else [])):
            log(stage="DELETE_TEMP_NOT_VERIFIED",retry=False);return 9
        log(stage="COMPLETE_VERIFIED",source_library=SOURCE_LIB,item_id=SOURCE_ID,
            native_copy_delete_verified=True,native_move_roundtrip_verified=True,
            structured_strength_preserved=True,temp_library_deleted=True,
            athlete_writes=0,plan_writes=0)
        return 0

if __name__=="__main__":
    try:raise SystemExit(asyncio.run(main()))
    except Stop as exc:
        log(stage="STOP_REVIEW",reason=str(exc),retry=False)
        raise SystemExit(2)
