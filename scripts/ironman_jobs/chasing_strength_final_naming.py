"""Guarded editorial final naming for seven undated CHASING Strength Builder library templates.
No athlete/calendar/plan write. Native item post once, provider readback, no retries on uncertainty.
The product itself remains a DRAFT in canonical Drive pending workout QA/release.
"""
from __future__ import annotations
import asyncio,hashlib,json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE

OWNER=2116886
LIB=3894341
OLD_LIB="CHASING THE SLOT | Forza — DRAFT NATIVE"
NEW_LIB="CHASING THE SLOT | Forza"
BASE="/rx/activity/v1/libraryContent/workoutLibrary"
TITLES={
 "330618":("[DRAFT] CHASING | Forza A60 | Adattamento full body + WarmUp","CHASING THE SLOT | Forza A60 | Adattamento full body + WarmUp"),
 "330621":("[DRAFT] CHASING | Forza B60 | Complementare full body + WarmUp","CHASING THE SLOT | Forza B60 | Complementare full body + WarmUp"),
 "330624":("[DRAFT] CHASING | Forza M60 | Mantenimento full body + WarmUp","CHASING THE SLOT | Forza M60 | Mantenimento full body + WarmUp"),
 "330626":("[DRAFT] CHASING | Forza D40 | Scarico tecnico + WarmUp","CHASING THE SLOT | Forza D40 | Scarico tecnico + WarmUp"),
 "330628":("[DRAFT] CHASING | Forza M45 | Specificita mantenimento + WarmUp","CHASING THE SLOT | Forza M45 | Specificita mantenimento + WarmUp"),
 "330629":("[DRAFT] CHASING | Forza M30 | Richiamo neurale minimo + WarmUp","CHASING THE SLOT | Forza M30 | Richiamo neurale minimo + WarmUp"),
 "330631":("[DRAFT] CHASING | Forza S60 | Sviluppo full body + WarmUp","CHASING THE SLOT | Forza S60 | Sviluppo full body + WarmUp")
}

def log(**kwargs):
    print(json.dumps(kwargs,ensure_ascii=False),flush=True)

def by_id(items):
    return {str(x.get("id")):x for x in items if isinstance(x,dict)}

def fingerprint(item):
    w=item.get("workout") or {}
    # Compare prescribed training, not volatile metadata or display title.
    protected={"blocks":w.get("blocks"),"instructions":w.get("instructions"),
               "totalTimePlanned":w.get("totalTimePlanned"),
               "calendarId":w.get("calendarId"),"prescribedDate":w.get("prescribedDate"),
               "workoutType":w.get("workoutType"),"native_id":w.get("id")}
    return hashlib.sha256(json.dumps(protected,ensure_ascii=False,sort_keys=True,separators=(",",":" )).encode()).hexdigest()

async def main():
  async with TPClient() as client:
    me=await client._get_user_data()
    lr=await client.get("/exerciselibrary/v2/libraries")
    libs=lr.data if not lr.is_error and isinstance(lr.data,list) else []
    lib=next((x for x in libs if x.get("exerciseLibraryId")==LIB),None)
    if (not isinstance(me,dict) or me.get("personId")!=OWNER or
        not lib or lib.get("ownerId")!=OWNER or lib.get("libraryName") not in (OLD_LIB,NEW_LIB)):
        log(stage="STOP_OWNER_OR_LIB",writes=0);return 2
    _,token,err=await _access(client)
    if err or not token:
        log(stage="STOP_AUTH",writes=0);return 2
    async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
        async def read():
            response=await h.get(STRENGTH_API_BASE+BASE+"/"+str(LIB),headers=_headers(token))
            if response.status_code!=200:raise RuntimeError("native read failed")
            raw=response.json(); data=raw.get("data") if isinstance(raw,dict) else raw
            if not isinstance(data,list):raise ValueError("unexpected native response")
            return data
        try:items=await read()
        except (httpx.RequestError,RuntimeError,ValueError):
            log(stage="STOP_READ",writes=0);return 3
        entries=by_id(items)
        if len(items)!=7 or set(entries)!=set(TITLES):
            log(stage="STOP_TEMPLATE_INVENTORY",count=len(items),writes=0);return 3
        originals={}
        for k,item in entries.items():
            w=item.get("workout")
            if (item.get("title") not in TITLES[k] or item.get("libraryId")!=LIB or
                item.get("workoutLibraryItemType")!="ActivityWorkoutTemplate" or
                not isinstance(w,dict) or w.get("workoutType")!="StructuredStrength" or
                w.get("calendarId") is not None or w.get("prescribedDate") is not None):
                log(stage="STOP_UNEXPECTED_TEMPLATE",id=k,writes=0);return 3
            originals[k]=fingerprint(item)
        log(stage="PREFLIGHT_PASS",count=7,old_lib=lib["libraryName"])
        modified=0
        for k,(_,new) in TITLES.items():
            if entries[k]["title"]==new:continue
            payload={"id":int(k),"libraryId":LIB,"title":new,
                     "workout":entries[k]["workout"],"workoutLibraryItemType":"ActivityWorkoutTemplate"}
            try:resp=await h.post(STRENGTH_API_BASE+BASE+"/save",headers=_headers(token),json=payload)
            except httpx.RequestError:
                log(stage="AMBIGUOUS_POST_STOP",id=k,retry=False);return 4
            try:now=by_id(await read())
            except (httpx.RequestError,RuntimeError,ValueError):
                log(stage="READBACK_FAILED_STOP",id=k,retry=False);return 4
            if (resp.status_code not in (200,201) or k not in now or now[k].get("title")!=new or
                fingerprint(now[k])!=originals[k] or set(now)!=set(TITLES)):
                log(stage="STOP_ITEM_QA",id=k,http=resp.status_code,retry=False);return 5
            entries=now
            modified+=1
            log(stage="ITEM_RENAMED_VERIFIED",id=k)
        # Folder naming is a separate metadata operation; never recreate/move/delete library.
        folder_result="ALREADY_OK"
        if lib["libraryName"]==OLD_LIB:
            merged=dict(lib);merged["libraryName"]=NEW_LIB
            try:result=await client.put(f"/exerciselibrary/v1/libraries/{LIB}",json=merged)
            except Exception:
                log(stage="FOLDER_PUT_UNCERTAIN",renamed_items=modified,retry=False);return 6
            check=await client.get("/exerciselibrary/v2/libraries")
            updated=next((x for x in (check.data if not check.is_error and isinstance(check.data,list) else []) if x.get("exerciseLibraryId")==LIB),None)
            if not updated or updated.get("ownerId")!=OWNER or updated.get("libraryName")!=NEW_LIB:
                log(stage="FOLDER_RENAME_UNVERIFIED",renamed_items=modified,
                    provider_error=getattr(result,"message",None),retry=False);return 6
            folder_result="RENAMED_VERIFIED"
        try:final=by_id(await read())
        except (httpx.RequestError,RuntimeError,ValueError):
            log(stage="FINAL_READ_ERROR",renamed_items=modified);return 7
        if set(final)!=set(TITLES) or any(final[k].get("title")!=TITLES[k][1] or fingerprint(final[k])!=originals[k] for k in TITLES):
            log(stage="FINAL_QA_FAILED",renamed_items=modified);return 7
        log(stage="COMPLETE",count=len(final),renamed_items=modified,folder=folder_result,
            all_native=True,all_undated=True,exercise_content_unchanged=True)
        return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
