"""Guarded classic Workout Library organization E2E canary.

Scope:
- owner 2116886
- source LAB library 3890637 only
- exact source item 14935062
- one temporary [MCP TEST] library
- create/rename/copy/delete-item/move-out/move-back/delete-library
- source item must finish byte-equivalent to provider baseline
- no athlete/calendar/plan writes
- no blind retry after ambiguous mutation; provider state is read before deciding
"""
from __future__ import annotations
import asyncio, copy, json
from typing import Any
from tp_mcp.client import TPClient

OWNER=2116886
SOURCE_LIB=3890637
SOURCE_NAME="[MCP TEST] Integration Lab"
SOURCE_ITEM=14935062
SOURCE_TITLE="[MCP TEST] Bike | Endurance semplice 30'"
TEMP_A="[MCP TEST] Organization Library Canary"
TEMP_B="[MCP TEST] Organization Library Canary | Renamed"
COPY_TITLE="[MCP TEST] Organization copy canary | Bike Endurance 30"

class Stop(Exception): pass
def log(**x): print(json.dumps(x,ensure_ascii=False,sort_keys=True),flush=True)
def must(v,m): 
    if not v: raise Stop(m)

def lib_id(x):
    v=x.get("exerciseLibraryId",x.get("id"))
    try:return int(v)
    except (TypeError,ValueError):return None

def item_id(x):
    v=x.get("exerciseLibraryItemId",x.get("id"))
    try:return int(v)
    except (TypeError,ValueError):return None

def canonical_item(x:dict[str,Any], *, ignore_title=False, ignore_lib=False, ignore_id=False):
    y=copy.deepcopy(x)
    # Ignore provider transient/display fields that can be populated on a write.
    for k in ("loaded","shared","selected","expanded"):
        y.pop(k,None)
    if ignore_title:
        y.pop("itemName",None);y.pop("title",None)
    if ignore_lib:
        y.pop("exerciseLibraryId",None)
    if ignore_id:
        y.pop("exerciseLibraryItemId",None);y.pop("id",None)
    return y

async def main()->int:
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")

        async def libs():
            r=await c.get("/exerciselibrary/v2/libraries")
            must(not r.is_error and isinstance(r.data,list),"LIBRARIES_READ_FAILED")
            return [x for x in r.data if isinstance(x,dict)]

        async def items(lib:int):
            r=await c.get(f"/exerciselibrary/v2/libraries/{lib}/items")
            must(not r.is_error and isinstance(r.data,list),f"ITEMS_READ_FAILED:{lib}")
            return [x for x in r.data if isinstance(x,dict)]

        async def exact_item(lib:int,iid:int):
            xs=await items(lib)
            found=[x for x in xs if item_id(x)==iid]
            must(len(found)<=1,f"DUPLICATE_ITEM_ID:{lib}:{iid}")
            return found[0] if found else None

        library_rows=await libs()
        source=next((x for x in library_rows if lib_id(x)==SOURCE_LIB),None)
        must(source and source.get("ownerId")==OWNER and source.get("libraryName")==SOURCE_NAME,
             "SOURCE_LIBRARY_DRIFT")
        src=await exact_item(SOURCE_LIB,SOURCE_ITEM)
        must(src is not None and src.get("itemName")==SOURCE_TITLE,"SOURCE_ITEM_DRIFT")
        baseline=canonical_item(src)

        # Refuse leftovers: this job is designed to be safely repeatable after a fully
        # completed prior run, but not to guess what to do with a partial temp library.
        temp=[x for x in library_rows if x.get("libraryName") in (TEMP_A,TEMP_B)]
        must(len(temp)<=1,"DUPLICATE_TEMP_LIBRARY")
        if temp:
            tid=lib_id(temp[0]);must(tid is not None,"TEMP_ID_MISSING")
            temp_items=await items(tid)
            must(not temp_items,"PARTIAL_TEMP_LIBRARY_NOT_EMPTY")
            # Existing empty temp from a previous interrupted run is safe to reuse.
            current_name=temp[0].get("libraryName")
            log(stage="PREFLIGHT_REUSE_EMPTY_TEMP",library_id=tid,name=current_name,writes=0)
        else:
            log(stage="PREFLIGHT_CREATE_TEMP",source_item=SOURCE_ITEM,writes=0)
            try:
                resp=await c._request("POST","/exerciselibrary/v1/libraries",
                                      json={"libraryName":TEMP_A,"ownerId":OWNER},_retry_on_401=False)
            except Exception:
                resp=None
            rb=await libs()
            matches=[x for x in rb if x.get("libraryName")==TEMP_A]
            if len(matches)!=1:
                log(stage="CREATE_TEMP_AMBIGUOUS_STOP",retry=False,writes="UNKNOWN");return 4
            tid=lib_id(matches[0]);must(tid is not None,"TEMP_ID_MISSING_AFTER_CREATE")
            current_name=TEMP_A
            log(stage="CREATE_TEMP_VERIFIED",library_id=tid,writes=1)

        # Rename canary.
        if current_name!=TEMP_B:
            try:
                resp=await c._request("PUT",f"/exerciselibrary/v1/libraries/{tid}/name",
                                      json={"value":TEMP_B},_retry_on_401=False)
            except Exception:
                resp=None
            rb=await libs()
            renamed=[x for x in rb if lib_id(x)==tid]
            if len(renamed)!=1 or renamed[0].get("libraryName")!=TEMP_B:
                log(stage="RENAME_TEMP_NOT_VERIFIED",retry=False,writes="UNKNOWN" if resp is None else 1);return 5
            log(stage="RENAME_TEMP_VERIFIED",library_id=tid,writes=1)

        # Copy classic item using provider-native POST. Preserve full structure/metadata,
        # changing only destination library and title.
        dest_items=await items(tid)
        previous=[x for x in dest_items if x.get("itemName")==COPY_TITLE]
        must(len(previous)<=1,"DUPLICATE_COPY_TITLE")
        if not previous:
            payload=copy.deepcopy(src)
            payload.pop("exerciseLibraryItemId",None);payload.pop("id",None)
            payload["exerciseLibraryId"]=tid
            payload["itemName"]=COPY_TITLE
            payload["title"]=COPY_TITLE
            try:
                resp=await c._request("POST",f"/exerciselibrary/v1/libraries/{tid}/items",
                                      json=payload,_retry_on_401=False)
            except Exception:
                resp=None
            after=await items(tid)
            previous=[x for x in after if x.get("itemName")==COPY_TITLE]
            if len(previous)!=1:
                log(stage="COPY_NOT_VERIFIED",retry=False,writes="UNKNOWN" if resp is None else 1);return 6
        copied=previous[0]; copied_id=item_id(copied);must(copied_id is not None,"COPY_ID_MISSING")
        # Compare provider content modulo destination/title/new ID.
        must(canonical_item(copied,ignore_title=True,ignore_lib=True,ignore_id=True)
             ==canonical_item(src,ignore_title=True,ignore_lib=True,ignore_id=True),
             "COPY_CONTENT_DRIFT")
        log(stage="COPY_VERIFIED",copy_id=copied_id,library_id=tid,writes=1)

        # Delete only the disposable copied item and verify absence.
        try:
            resp=await c._request("DELETE",f"/exerciselibrary/v1/libraries/{tid}/items/{copied_id}",
                                  _retry_on_401=False)
        except Exception:
            resp=None
        gone=await exact_item(tid,copied_id)
        if gone is not None:
            log(stage="DELETE_COPY_NOT_VERIFIED",retry=False,writes="UNKNOWN" if resp is None else 1);return 7
        log(stage="DELETE_COPY_VERIFIED",copy_id=copied_id,writes=1)

        # Native classic move: same item ID, destination URL + exerciseLibraryId change.
        current_src=await exact_item(SOURCE_LIB,SOURCE_ITEM)
        current_dst=await exact_item(tid,SOURCE_ITEM)
        must(current_src is not None and current_dst is None,"PRE_MOVE_MEMBERSHIP_DRIFT")
        move_payload=copy.deepcopy(current_src);move_payload["exerciseLibraryId"]=tid
        try:
            resp=await c._request("PUT",f"/exerciselibrary/v1/libraries/{tid}/items/{SOURCE_ITEM}",
                                  json=move_payload,_retry_on_401=False)
        except Exception:
            resp=None
        src_after=await exact_item(SOURCE_LIB,SOURCE_ITEM)
        dst_after=await exact_item(tid,SOURCE_ITEM)
        if src_after is not None or dst_after is None:
            log(stage="MOVE_OUT_NOT_VERIFIED",source_present=src_after is not None,
                dest_present=dst_after is not None,retry=False,writes="UNKNOWN" if resp is None else 1);return 8
        must(canonical_item(dst_after,ignore_lib=True)==canonical_item(src,ignore_lib=True),
             "MOVE_OUT_CONTENT_DRIFT")
        log(stage="MOVE_OUT_VERIFIED",item_id=SOURCE_ITEM,to_library=tid,writes=1)

        # Move exact same item back to LAB.
        back_payload=copy.deepcopy(dst_after);back_payload["exerciseLibraryId"]=SOURCE_LIB
        try:
            resp=await c._request("PUT",f"/exerciselibrary/v1/libraries/{SOURCE_LIB}/items/{SOURCE_ITEM}",
                                  json=back_payload,_retry_on_401=False)
        except Exception:
            resp=None
        restored=await exact_item(SOURCE_LIB,SOURCE_ITEM)
        still_temp=await exact_item(tid,SOURCE_ITEM)
        if restored is None or still_temp is not None:
            log(stage="MOVE_BACK_NOT_VERIFIED",retry=False,writes="UNKNOWN" if resp is None else 1);return 9
        must(canonical_item(restored)==baseline,"SOURCE_ITEM_NOT_EXACTLY_RESTORED")
        log(stage="MOVE_BACK_VERIFIED",item_id=SOURCE_ITEM,writes=1)

        must(not await items(tid),"TEMP_NOT_EMPTY_BEFORE_DELETE")
        try:
            resp=await c._request("DELETE",f"/exerciselibrary/v1/libraries/{tid}",
                                  _retry_on_401=False)
        except Exception:
            resp=None
        final_libs=await libs()
        if any(lib_id(x)==tid for x in final_libs):
            log(stage="DELETE_TEMP_NOT_VERIFIED",retry=False,writes="UNKNOWN" if resp is None else 1);return 10
        must(canonical_item(await exact_item(SOURCE_LIB,SOURCE_ITEM))==baseline,"FINAL_SOURCE_DRIFT")
        log(stage="COMPLETE_VERIFIED",source_library=SOURCE_LIB,item_id=SOURCE_ITEM,
            temp_library_deleted=True,copy_delete_verified=True,move_roundtrip_verified=True,
            athlete_writes=0,plan_writes=0)
        return 0

if __name__=="__main__":
    try: raise SystemExit(asyncio.run(main()))
    except Stop as exc:
        log(stage="STOP_REVIEW",reason=str(exc),retry=False)
        raise SystemExit(2)
