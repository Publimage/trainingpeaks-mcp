"""Rename five existing coach Workout Libraries for shared IT cross-product use.
In-place metadata ONLY, preserving all item IDs, structures, native Strength and applied plans.
No creation, deletion, copy, athlete calendar or plan write. Fail on name collisions.
"""
from __future__ import annotations
import asyncio, json
from tp_mcp.client import TPClient

OWNER=2116886
NAMES={
 3891872:("IRONMAN MASTER | Nuoto","ALBERTO FAZI ENDURANCE | Nuoto | IT"),
 3892601:("IRONMAN MASTER | Bici — DEDUP VERIFIED","ALBERTO FAZI ENDURANCE | Bici | IT"),
 3892602:("IRONMAN MASTER | Corsa — DEDUP VERIFIED","ALBERTO FAZI ENDURANCE | Corsa | IT"),
 3891875:("IRONMAN MASTER | Forza","ALBERTO FAZI ENDURANCE | Forza | IT"),
 3892900:("IRONMAN MASTER | Note","ALBERTO FAZI ENDURANCE | Note | IT")
}

def log(**kw):print(json.dumps(kw,ensure_ascii=False),flush=True)

def index(libraries):
 return {int(x["exerciseLibraryId"]):x for x in libraries
         if isinstance(x,dict) and x.get("exerciseLibraryId") is not None}

async def main():
 async with TPClient() as client:
  user=await client._get_user_data()
  if not isinstance(user,dict) or user.get("personId")!=OWNER:
   log(stage="STOP_OWNER",writes=0);return 2
  async def fetch():
   result=await client.get("/exerciselibrary/v2/libraries")
   if result.is_error or not isinstance(result.data,list):
    raise RuntimeError("Library inventory read unavailable")
   return index(result.data)
  try:current=await fetch()
  except Exception:
   log(stage="STOP_READ",writes=0);return 2
  if len(current)!=len(set(current)):
   log(stage="STOP_NON_UNIQUE_IDS",writes=0);return 3
  new_names={b for a,b in NAMES.values()}
  if len(new_names)!=len(NAMES):
   log(stage="STOP_COLLISION_CONFIG",writes=0);return 3
  for lid,(old,new) in NAMES.items():
   item=current.get(lid)
   if not item or item.get("ownerId")!=OWNER or item.get("libraryName") not in (old,new):
    log(stage="STOP_UNEXPECTED_TARGET",library=lid,writes=0);return 3
  for lid,item in current.items():
   if lid not in NAMES and item.get("ownerId")==OWNER and item.get("libraryName") in new_names:
    log(stage="STOP_EXISTING_TARGET_NAME",library=lid,writes=0);return 3
  log(stage="PREFLIGHT_PASS",targets=len(NAMES),rename_pending=sum(current[i]["libraryName"]!=new for i,(_,new) in NAMES.items()),writes=0)
  modified=[]
  for lid,(old,new) in NAMES.items():
   if current[lid]["libraryName"]==new:continue
   try:resp=await client.put(f"/exerciselibrary/v1/libraries/{lid}/name",json={"value":new})
   except Exception:
    log(stage="UNCERTAIN_PUT_STOP",id=lid,already_verified=modified,retry=False);return 4
   try:now=await fetch()
   except Exception:
    log(stage="UNCERTAIN_READBACK_STOP",id=lid,already_verified=modified,retry=False);return 4
   if (now.get(lid,{}).get("libraryName")!=new or
       now.get(lid,{}).get("ownerId")!=OWNER or
       {k:now.get(k,{}).get("libraryName") for k in NAMES if k!=lid}!=
       {k:current.get(k,{}).get("libraryName") for k in NAMES if k!=lid}):
    log(stage="READBACK_NOT_PASS_STOP",id=lid,already_verified=modified,
        code=getattr(resp,"status_code",None),retry=False);return 5
   modified.append(lid)
   current=now
   log(stage="RENAME_VERIFIED",id=lid,new_name=new,writes=1)
  log(stage="COMPLETE",renamed=modified,targets=len(NAMES),
      live=[{"id":lid,"name":current[lid]["libraryName"]} for lid in NAMES],
      unchanged_ids=True,unchanged_templates_by_metadata_only=True,
      no_athlete_or_plan_write=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
