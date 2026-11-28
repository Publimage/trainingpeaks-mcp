"""READ-ONLY recovery diagnostic after native Strength move canary drift.

Inspects exact source/temp membership and reports only structural field diffs and
semantic signatures. No provider writes.
"""
from __future__ import annotations
import asyncio,json,hashlib,httpx
from typing import Any
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE

OWNER=2116886
SOURCE=3890637
TEMP=3902999
ITEM=330612
READ="/rx/activity/v1/libraryContent/workoutLibrary/{lib}"

def items(raw):
    data=raw.get("data") if isinstance(raw,dict) else raw
    return [x for x in data if isinstance(x,dict)] if isinstance(data,list) else []

def sig(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()

def compact(x):
    if not isinstance(x,dict):return None
    w=x.get("workout") if isinstance(x.get("workout"),dict) else {}
    blocks=w.get("blocks") or []
    return {
      "id":x.get("id"),"libraryId":x.get("libraryId"),"title":x.get("title"),
      "workoutLibraryItemType":x.get("workoutLibraryItemType"),
      "top_keys":sorted(x),"workout_keys":sorted(w),
      "workoutType":w.get("workoutType"),
      "block_count":len(blocks),
      "prescription_counts":[len(b.get("prescriptions") or []) for b in blocks],
      "top_sha":sig(x),
      "workout_sha":sig(w),
      "blocks_sha":sig(blocks),
    }

async def main():
    async with TPClient() as c:
      me=await c._get_user_data()
      if not isinstance(me,dict) or me.get("personId")!=OWNER:
        print(json.dumps({"stage":"STOP_OWNER","writes":0}));return 2
      _,token,error=await _access(c)
      if error or not token:
        print(json.dumps({"stage":"STOP_AUTH","writes":0}));return 2
      async with httpx.AsyncClient(timeout=20,follow_redirects=False) as h:
        out={}
        for lib in (SOURCE,TEMP):
          r=await h.get(STRENGTH_API_BASE+READ.format(lib=lib),headers=_headers(token))
          if r.status_code!=200:
            out[str(lib)]={"http":r.status_code};continue
          match=[x for x in items(r.json()) if int(x.get("id") or 0)==ITEM]
          out[str(lib)]={"count":len(match),"item":compact(match[0]) if len(match)==1 else None}
      libs=await c.get("/exerciselibrary/v2/libraries")
      temp_meta=None
      if not libs.is_error and isinstance(libs.data,list):
        temp_meta=next(({"id":x.get("exerciseLibraryId"),"name":x.get("libraryName"),
                         "ownerId":x.get("ownerId")} for x in libs.data
                        if x.get("exerciseLibraryId")==TEMP),None)
      print(json.dumps({"stage":"RECOVERY_STATE","source":out[str(SOURCE)],
                        "temp":out[str(TEMP)],"temp_library":temp_meta,
                        "provider_writes":0},ensure_ascii=False),flush=True)
      return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
