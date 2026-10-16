"""Beginner 679801 native Strength Builder plan writers.

Two narrowly-scoped tools:
1) create native StructuredStrength twins in batches of <=8;
2) delete the corresponding classic Strength sources only after native twin readback.
No athlete calendar writes, no other plans, no library writes.
"""
from __future__ import annotations
from datetime import date as dt, timedelta
from typing import Any
import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools.strength import (
    STRENGTH_API_BASE, STRENGTH_TIMEOUT, _access, _headers, _build_payload, _validate_blocks, _err
)

PLAN_ID=679801
PLAN_TITLE="ALBERTO FAZI ENDURANCE | First Ironman | 24 settimane | Beginner | Smart Start incluso | Italiano"
PLAN_START="2026-09-21"
OWNER_ID=2116886
SOURCE_IDS={
3978611861,3978611904,3978611883,3978611911,3978611902,3978611865,
3978611892,3978611927,3978612069,3978611975,3978611992,3978612084,
3978612013,3978611928,3978612064,3978611980,3978612004,3978611989,
3978611990,3978611991,3978611999,3978611959,3978612071,3978611979,
3978612092,3978611983,3978612073,3978612076,3978612090,3978612133,
3978612027,3978612031,3978612042,3978612100,3978611945,3978611956,
}

async def _plan(client: TPClient) -> dict[str,Any] | None:
    r=await client.get(f"/plans/v1/plans/{PLAN_ID}")
    if r.is_error or not isinstance(r.data,dict):
        return None
    return r.data

def _plan_ok(p: dict[str,Any], expected_count:int) -> bool:
    return (
        p.get("planId")==PLAN_ID
        and (p.get("title") or "").strip()==PLAN_TITLE
        and (p.get("startDate") or "")[:10]==PLAN_START
        and p.get("weekCount")==24
        and p.get("isPublic") is True
        and p.get("workoutCount")==expected_count
        and p.get("ownerPersonId")==OWNER_ID
    )

async def _classic_range(client:TPClient) -> list[dict[str,Any]]:
    end=(dt.fromisoformat(PLAN_START)+timedelta(weeks=24,days=2)).isoformat()
    r=await client.get(f"/plans/v1/plans/{PLAN_ID}/workouts/{PLAN_START}/{end}")
    if r.is_error or not isinstance(r.data,list):
        raise RuntimeError("CLASSIC_PLAN_READ_FAILED")
    return r.data

async def _native_range(h:httpx.AsyncClient, access:str) -> list[dict[str,Any]]:
    end=(dt.fromisoformat(PLAN_START)+timedelta(weeks=24,days=2)).isoformat()
    r=await h.get(
        f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{PLAN_ID}/workouts/{PLAN_START}/{end}",
        headers=_headers(access),
    )
    if r.status_code!=200:
        raise RuntimeError("NATIVE_PLAN_READ_FAILED")
    data=r.json()
    data=data.get("data") if isinstance(data,dict) else data
    if not isinstance(data,list):
        raise RuntimeError("NATIVE_PLAN_SHAPE")
    return data

def _nkey(x:dict[str,Any]) -> tuple[str,str]:
    return ((x.get("title") or "").strip(),str(x.get("prescribedDate") or "")[:10])

async def tp_batch_add_beginner_strength(
    items:list[dict[str,Any]],
    expected_plan_count:int,
    dry_run:bool=True,
) -> dict[str,Any]:
    """Create 1-8 native StructuredStrength twins in public Beginner 679801 only."""
    if type(dry_run) is not bool or type(expected_plan_count) is not int:
        return _err("VALIDATION_ERROR","Require boolean dry_run and integer expected_plan_count.")
    if not isinstance(items,list) or not 1<=len(items)<=8:
        return _err("VALIDATION_ERROR","Require 1-8 items.")
    manifest=[]; seen=set()
    for x in items:
        if not isinstance(x,dict):
            return _err("VALIDATION_ERROR","Each item must be an object.")
        sid=x.get("source_workout_id"); week=x.get("week"); day=x.get("day")
        title=x.get("title"); instructions=x.get("instructions"); blocks=x.get("blocks")
        if (type(sid) is not int or sid not in SOURCE_IDS or type(week) is not int or not 1<=week<=23
            or type(day) is not int or not 0<=day<=6 or not isinstance(title,str) or len(title)<8
            or not isinstance(instructions,str) or len(instructions)<100):
            return _err("VALIDATION_ERROR",f"Invalid item identity for {sid}.")
        invalid=_validate_blocks(blocks)
        if invalid:
            return _err("VALIDATION_ERROR",f"{sid}: {invalid}")
        d=(dt.fromisoformat(PLAN_START)+timedelta(days=(week-1)*7+day)).isoformat()
        sig=(sid,d,title)
        if sig in seen:
            return _err("VALIDATION_ERROR","Duplicate item.")
        seen.add(sig)
        manifest.append({"sid":sid,"date":d,"title":title,"instructions":instructions,"blocks":blocks,
            "sets":sum(len(e["sets"]) for b in blocks for e in b["exercises"])})
    async with TPClient() as client:
        p=await _plan(client)
        if not p or not _plan_ok(p,expected_plan_count):
            return _err("PROTECTED_RESOURCE","Beginner plan identity/count drift.")
        classic=await _classic_range(client)
        byid={int(w.get("workoutId") or 0):w for w in classic}
        for z in manifest:
            w=byid.get(z["sid"])
            if not w or w.get("workoutTypeValueId")!=9 or w.get("structure") is not None:
                return _err("SOURCE_DRIFT",f"Classic Strength source drift: {z['sid']}")
            if str(w.get("workoutDay") or "")[:10]!=z["date"]:
                return _err("SOURCE_DATE_DRIFT",str(z["sid"]))
        if dry_run:
            return {"success":True,"dry_run":True,"plan_id":PLAN_ID,"batch_count":len(manifest),
                    "expected_plan_count":expected_plan_count,
                    "manifest":[{"source_workout_id":z["sid"],"date":z["date"],"title":z["title"],"sets":z["sets"]} for z in manifest],
                    "write_performed":False}
        _,access,err=await _access(client)
        if err: return err
        try:
            calendar_id=int(p.get("planPersonId"))
        except (TypeError,ValueError):
            calendar_id=0
        if calendar_id<=0:
            return _err("PLAN_PERSON_UNAVAILABLE","Beginner planPersonId unavailable.")
        saved=[]
        async with httpx.AsyncClient(timeout=STRENGTH_TIMEOUT) as h:
            for z in manifest:
                fresh=await _plan(client)
                if not fresh or fresh.get("workoutCount")!=expected_plan_count+len(saved):
                    return {"success":False,"error_code":"PLAN_DRIFT","partial_writes":saved}
                current=await _native_range(h,access)
                if any(_nkey(v)==(z["title"],z["date"]) for v in current):
                    return {"success":False,"error_code":"ALREADY_EXISTS_IN_TARGET","partial_writes":saved,
                            "source_workout_id":z["sid"]}
                payload=_build_payload(calendar_id,z["date"],z["title"],z["blocks"],z["instructions"])
                try:
                    resp=await h.post(
                        f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{PLAN_ID}/workouts/save",
                        headers=_headers(access),json=payload,
                    )
                except httpx.RequestError:
                    after=await _native_range(h,access)
                    matches=[v for v in after if _nkey(v)==(z["title"],z["date"])]
                    if len(matches)==1:
                        wid=str(matches[0].get("id") or matches[0].get("workoutId"))
                        saved.append({"source_workout_id":z["sid"],"workout_id":wid,"title":z["title"],"date":z["date"]})
                        continue
                    return {"success":False,"error_code":"AMBIGUOUS_POST","partial_writes":saved,
                            "never_retry_without_readback":True}
                if resp.status_code!=200:
                    return {"success":False,"error_code":"PROVIDER_REJECTED","http_status":resp.status_code,
                            "partial_writes":saved}
                body=resp.json().get("data") or {}
                native_id=str(body.get("id") or payload["id"])
                detail=await h.get(f"{STRENGTH_API_BASE}/rx/activity/v1/workouts/{native_id}",headers=_headers(access))
                after=await _native_range(h,access)
                ref=await _plan(client)
                if detail.status_code!=200 or not ref:
                    return {"success":False,"error_code":"READBACK_UNAVAILABLE","partial_writes":saved}
                nd=detail.json().get("data") or {}
                member=any(str(v.get("id") or v.get("workoutId"))==native_id for v in after)
                videos=all((pr.get("exercise") or {}).get("videoUrl") for b in nd.get("blocks") or [] for pr in b.get("prescriptions") or [])
                if (nd.get("workoutType")!="StructuredStrength" or nd.get("title")!=z["title"]
                    or str(nd.get("prescribedDate") or "")[:10]!=z["date"] or nd.get("calendarId")!=calendar_id
                    or (nd.get("snapshot") or {}).get("totalSets")!=z["sets"] or not member or not videos
                    or ref.get("workoutCount")!=expected_plan_count+len(saved)+1):
                    return {"success":False,"error_code":"READBACK_MISMATCH","partial_writes":saved,
                            "unverified_workout_id":native_id}
                saved.append({"source_workout_id":z["sid"],"workout_id":native_id,"title":z["title"],"date":z["date"],"sets":z["sets"]})
        return {"success":True,"dry_run":False,"plan_id":PLAN_ID,"written":len(saved),
                "workouts":saved,"count_after":expected_plan_count+len(saved)}

async def tp_batch_delete_beginner_classic_strength(
    items:list[dict[str,Any]],
    expected_plan_count:int,
    dry_run:bool=True,
) -> dict[str,Any]:
    """Delete 1-8 exact classic Beginner Strength sources only after native twins exist."""
    if type(dry_run) is not bool or type(expected_plan_count) is not int:
        return _err("VALIDATION_ERROR","Require boolean dry_run and integer expected_plan_count.")
    if not isinstance(items,list) or not 1<=len(items)<=8:
        return _err("VALIDATION_ERROR","Require 1-8 items.")
    manifest=[]
    for x in items:
        sid=x.get("source_workout_id") if isinstance(x,dict) else None
        title=x.get("native_title") if isinstance(x,dict) else None
        d=x.get("date") if isinstance(x,dict) else None
        if type(sid) is not int or sid not in SOURCE_IDS or not isinstance(title,str) or not isinstance(d,str):
            return _err("VALIDATION_ERROR","Invalid delete item.")
        manifest.append({"sid":sid,"title":title,"date":d[:10]})
    async with TPClient() as client:
        p=await _plan(client)
        if not p or not _plan_ok(p,expected_plan_count):
            return _err("PROTECTED_RESOURCE","Beginner plan identity/count drift.")
        _,access,err=await _access(client)
        if err:return err
        deleted=[]
        async with httpx.AsyncClient(timeout=STRENGTH_TIMEOUT) as h:
            for z in manifest:
                classic=await _classic_range(client)
                byid={int(w.get("workoutId") or 0):w for w in classic}
                source=byid.get(z["sid"])
                if source is None:
                    return {"success":False,"error_code":"SOURCE_ALREADY_MISSING","partial_deletes":deleted}
                if source.get("workoutTypeValueId")!=9 or source.get("structure") is not None or str(source.get("workoutDay") or "")[:10]!=z["date"]:
                    return {"success":False,"error_code":"SOURCE_DRIFT","partial_deletes":deleted}
                native=await _native_range(h,access)
                twins=[v for v in native if _nkey(v)==(z["title"],z["date"])]
                if len(twins)!=1:
                    return {"success":False,"error_code":"NATIVE_TWIN_NOT_EXACT","partial_deletes":deleted}
                if dry_run:
                    continue
                res=await client._request("DELETE",f"/plans/v1/plans/{PLAN_ID}/workouts/{z['sid']}",_retry_on_401=False)
                after=await _classic_range(client)
                if any(int(w.get("workoutId") or 0)==z["sid"] for w in after):
                    return {"success":False,"error_code":"DELETE_UNVERIFIED","partial_deletes":deleted,
                            "never_retry_without_readback":True}
                # Native twin must survive source deletion.
                native_after=await _native_range(h,access)
                if len([v for v in native_after if _nkey(v)==(z["title"],z["date"])])!=1:
                    return {"success":False,"error_code":"NATIVE_TWIN_LOST","partial_deletes":deleted}
                deleted.append(z["sid"])
        if dry_run:
            return {"success":True,"dry_run":True,"plan_id":PLAN_ID,"batch_count":len(manifest),"write_performed":False}
        final=await _plan(client)
        return {"success":True,"dry_run":False,"plan_id":PLAN_ID,"deleted":len(deleted),
                "source_workout_ids":deleted,"count_after":final.get("workoutCount") if final else None}
