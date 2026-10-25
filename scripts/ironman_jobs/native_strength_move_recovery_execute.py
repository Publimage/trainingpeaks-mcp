"""Guarded recovery: move native StructuredStrength item 330612 back to LAB.

State was independently verified after the organization canary stopped:
source 3890637 absent, temp 3902999 contains exactly item 330612.
This job uses the provider's CURRENT object as the recovery baseline, changes
only libraryId, verifies exact prescribed blocks, then removes empty temp lib.
"""
from __future__ import annotations
import asyncio,copy,hashlib,json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE

OWNER=2116886
SOURCE=3890637
TEMP=3902999
ITEM=330612
TITLE="[MCP TEST] CHASING | Forza A | Base full body 60min + WarmUp"
READ="/rx/activity/v1/libraryContent/workoutLibrary/{lib}"
SAVE="/rx/activity/v1/libraryContent/workoutLibrary/save"

class Stop(Exception):pass
def log(**x):print(json.dumps(x,ensure_ascii=False,sort_keys=True),flush=True)
def must(v,m):
    if not v:raise Stop(m)
def items(raw):
    data=raw.get("data") if isinstance(raw,dict) else raw
    return [x for x in data if isinstance(x,dict)] if isinstance(data,list) else []
def iid(x):
    try:return int(x.get("id"))
    except (TypeError,ValueError):return None
def digest(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()

async def main()->int:
  async with TPClient() as c:
    me=await c._get_user_data()
    must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
    _,token,error=await _access(c);must(not error and token,"STRENGTH_AUTH_FAILED")
    headers=_headers(token)
    async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
      async def read(lib):
        r=await h.get(STRENGTH_API_BASE+READ.format(lib=lib),headers=headers)
        must(r.status_code==200,f"NATIVE_READ_FAILED:{lib}:{r.status_code}")
        return items(r.json())
      src=[x for x in await read(SOURCE) if iid(x)==ITEM]
      tmp=[x for x in await read(TEMP) if iid(x)==ITEM]
      must(not src and len(tmp)==1,"RECOVERY_PRECONDITION_DRIFT")
      current=tmp[0]
      must(current.get("title")==TITLE,"RECOVERY_TITLE_DRIFT")
      must(current.get("workoutLibraryItemType")=="ActivityWorkoutTemplate","RECOVERY_TYPE_DRIFT")
      w=current.get("workout");must(isinstance(w,dict) and w.get("workoutType")=="StructuredStrength","RECOVERY_WORKOUT_TYPE")
      blocks=w.get("blocks") or [];must(len(blocks)==9,"RECOVERY_BLOCK_COUNT")
      block_sha=digest(blocks)
      prescription_counts=[len(b.get("prescriptions") or []) for b in blocks]
      payload={"id":current["id"],"libraryId":SOURCE,"title":current["title"],
               "workout":current["workout"],"workoutLibraryItemType":current["workoutLibraryItemType"]}
      log(stage="PREFLIGHT",block_sha=block_sha,prescription_counts=prescription_counts,writes=0)
      try:
        rr=await h.post(STRENGTH_API_BASE+SAVE,json=payload,headers=headers)
        http_status=rr.status_code
      except httpx.RequestError:
        http_status=None
      src_after=[x for x in await read(SOURCE) if iid(x)==ITEM]
      tmp_after=[x for x in await read(TEMP) if iid(x)==ITEM]
      if len(src_after)!=1 or tmp_after:
        log(stage="RECOVERY_MOVE_NOT_VERIFIED",http=http_status,source=len(src_after),temp=len(tmp_after),retry=False)
        return 4
      restored=src_after[0]
      rw=restored.get("workout") if isinstance(restored.get("workout"),dict) else {}
      rblocks=rw.get("blocks") or []
      must(restored.get("title")==TITLE,"RESTORED_TITLE_DRIFT")
      must(restored.get("workoutLibraryItemType")=="ActivityWorkoutTemplate","RESTORED_TYPE_DRIFT")
      must(rw.get("workoutType")=="StructuredStrength","RESTORED_WORKOUT_TYPE_DRIFT")
      must(digest(rblocks)==block_sha,"RESTORED_BLOCKS_DRIFT")
      must([len(b.get("prescriptions") or []) for b in rblocks]==prescription_counts,"RESTORED_PRESCRIPTIONS_DRIFT")
      log(stage="RECOVERY_MOVE_VERIFIED",item_id=ITEM,block_sha=block_sha,writes=1)

    classic=await c.get(f"/exerciselibrary/v2/libraries/{TEMP}/items")
    must(not classic.is_error and isinstance(classic.data,list) and not classic.data,"TEMP_CLASSIC_NOT_EMPTY")
    # Native read already proved item moved out; delete empty container.
    try:
      resp=await c._request("DELETE",f"/exerciselibrary/v1/libraries/{TEMP}",_retry_on_401=False)
    except Exception:
      resp=None
    libs=await c.get("/exerciselibrary/v2/libraries")
    present=not libs.is_error and isinstance(libs.data,list) and any(x.get("exerciseLibraryId")==TEMP for x in libs.data)
    if present:
      log(stage="TEMP_DELETE_NOT_VERIFIED",retry=False);return 5
    log(stage="COMPLETE_VERIFIED",item_id=ITEM,source_library=SOURCE,
        structured_strength_blocks_preserved=True,temp_library_deleted=True,
        athlete_writes=0,plan_writes=0)
    return 0

if __name__=="__main__":
  try:raise SystemExit(asyncio.run(main()))
  except Stop as exc:
    log(stage="STOP_REVIEW",reason=str(exc),retry=False)
    raise SystemExit(2)
