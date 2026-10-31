"""Correct display block titles in five undated native Chasing Strength templates.

Guarded exact provider IDs, no exercise/set change, no calendar associations.
Readback after every in-place update; no retry on ambiguous response.
"""
from __future__ import annotations
import asyncio,json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
LIB=3894341
BASE="/rx/activity/v1/libraryContent/workoutLibrary"
NAME_BY_ID={
 "144":"Goblet Squat","154":"Romanian Deadlift","165":"Weighted Step Up",
 "520":"DB Seated Single Leg Calf Raise","516":"DB Row","5366":"Push Up",
 "79":"Side Plank","579":"Glute Bridge","553":"Elevated Body Weight Calf Raise",
 "616":"Incline Push Up","5312":"Ipsilateral Dead Bug","158":"Split Squat",
 "151":"Single Arm DB Row"
}
TARGETS={
 "330624":["144","154","165","520","516","5366","79"],
 "330626":["144","579","553","516","616","5312"],
 "330628":["144","154","553","516","5366","79"],
 "330629":["144","553","516","5366","79"],
 "330631":["144","154","158","553","151","5366","79","5312"]
}

def verify(item,wanted):
    workout=item.get("workout") or {}; bs=workout.get("blocks") or []
    ex_ids=[str(p.get("exercise",{}).get("id")) for b in bs[1:] for p in b.get("prescriptions") or []]
    labels=[b.get("title") for b in bs[1:]]
    return (item.get("libraryId")==LIB and item.get("workoutLibraryItemType")=="ActivityWorkoutTemplate"
            and workout.get("workoutType")=="StructuredStrength"
            and workout.get("calendarId") is None and workout.get("prescribedDate") is None
            and bs[0].get("blockType")=="WarmUp" and ex_ids==wanted
            and labels==[f"{i}. {NAME_BY_ID[eid]}" for i,eid in enumerate(wanted,1)])

def log(**args):print(json.dumps(args,ensure_ascii=False),flush=True)

async def main():
    async with TPClient() as client:
        user=await client._get_user_data()
        libs=await client.get("/exerciselibrary/v2/libraries")
        lib=next((x for x in libs.data if x.get("exerciseLibraryId")==LIB),None) if not libs.is_error and isinstance(libs.data,list) else None
        if not user or user.get("personId")!=2116886 or not lib or lib.get("ownerId")!=2116886 or lib.get("libraryName")!="CHASING THE SLOT | Forza — DRAFT NATIVE":
            log(stage="STOP_OWNER");return 2
        _,token,err=await _access(client)
        if err or not token:return 2
        async with httpx.AsyncClient(timeout=22,follow_redirects=False) as h:
            async def read():
                r=await h.get(STRENGTH_API_BASE+BASE+"/"+str(LIB),headers=_headers(token))
                if r.status_code!=200:raise ValueError("read")
                return r.json()
            try:arr=await read()
            except (httpx.RequestError,ValueError):return 2
            if len(arr)!=7 or len(set(x.get("id") for x in arr))!=7:return 3
            changed=[]
            for item_id,wanted in TARGETS.items():
                match=[x for x in arr if str(x.get("id"))==item_id]
                if len(match)!=1:return 3
                item=match[0]
                if verify(item,wanted):
                    changed.append({"id":item_id,"status":"ALREADY_OK"});continue
                w=dict(item.get("workout") or {})
                bs=w.get("blocks") or []
                ids=[str(p.get("exercise",{}).get("id")) for b in bs[1:] for p in b.get("prescriptions") or []]
                if (w.get("calendarId") is not None or w.get("prescribedDate") is not None
                    or w.get("workoutType")!="StructuredStrength" or len(bs)!=len(wanted)+1
                    or bs[0].get("blockType")!="WarmUp" or ids!=wanted
                    or [b.get("title") for b in bs[1:]] != [f"{i}. {eid}" for i,eid in enumerate(wanted,1)]):
                    log(stage="STOP_DRIFT",id=item_id);return 3
                new_blocks=[dict(b) for b in bs]
                for i,eid in enumerate(wanted,1):
                    new_blocks[i]["title"]=f"{i}. {NAME_BY_ID[eid]}"
                w["blocks"]=new_blocks
                payload={"id":int(item_id),"libraryId":LIB,"title":item["title"],
                         "workout":w,"workoutLibraryItemType":"ActivityWorkoutTemplate"}
                try:r=await h.post(STRENGTH_API_BASE+BASE+"/save",headers=_headers(token),json=payload)
                except httpx.RequestError:
                    log(stage="AMBIGUOUS_POST",id=item_id,retry=False);return 4
                try:arr=await read()
                except (httpx.RequestError,ValueError):
                    log(stage="READBACK_FAILED",id=item_id,retry=False);return 4
                item2=[x for x in arr if str(x.get("id"))==item_id]
                if r.status_code!=200 or len(item2)!=1 or not verify(item2[0],wanted):
                    log(stage="STOP_QA",id=item_id,http=r.status_code,retry=False);return 5
                changed.append({"id":item_id,"status":"VERIFIED"})
                log(stage="PATCH_VERIFIED",id=item_id,exercise_count=len(wanted))
            log(stage="COMPLETE",count=len(arr),fixed=changed,no_dates=True)
            return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
