"""Create/assemble one private reusable Strength Training Plan from approved manifest.

Reuse proven plan creation code from chasing_plan_create.py and Peaksware-native
plan Strength save from chasing_strength_batch_w01_w08.py, without athlete writes.
The manifest is the sole input. Every POST guarded with immediate readback;
ambiguous POST never retried. Existing exact items are validated and skipped.
"""
from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import date, timedelta
from pathlib import Path

import httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access, _headers, STRENGTH_API_BASE

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/ironman_native_strength_plan_assembly.json"
LIB_MANIFEST = ROOT / "data/ironman_strength_library_manifest.json"
OWNER = 2116886
LIBRARY_ID = 3891875
LIBRARY_NAME = "ALBERTO FAZI ENDURANCE | Forza | IT"
TITLE = "ALBERTO FAZI ENDURANCE | WINTER FOUNDATION | 8 settimane | Italiano"
ANCHOR = "2027-01-04"
NATIVE_LIB_PATH = f"/rx/activity/v1/libraryContent/workoutLibrary/{LIBRARY_ID}"

def emit(**data):
    print(json.dumps(data, ensure_ascii=False, default=str), flush=True)

def load_manifest():
    p = json.loads(MANIFEST.read_text(encoding="utf-8"))
    src = json.loads(LIB_MANIFEST.read_text(encoding="utf-8"))
    if not (
        p.get("schema") == "IRONMAN_NATIVE_STRENGTH_PLAN_ASSEMBLY_V1"
        and p.get("owner_person_id") == OWNER
        and p.get("library_id") == LIBRARY_ID
        and p.get("plan_title") == TITLE
        and p.get("private") is True
        and p.get("price") is None
        and p.get("weeks") == 8
        and p.get("technical_anchor_monday") == ANCHOR
        and p.get("is_training_plan_not_athlete_calendar") is True
        and src.get("native_status") == "PUBLISHED_NATIVE_LIBRARY_PROVIDER_VERIFIED"
        and src.get("provider_library_id") == LIBRARY_ID
    ):
        raise ValueError("INVALID_MANIFEST_SCOPE")
    entries = p.get("workouts") or []
    canonical = {x["canonical_uid"]:x for x in src["items"]}
    if len(entries) != 16 or len(canonical) != 16:
        raise ValueError("NOT_16_PRESCRIPTIONS")
    if date.fromisoformat(ANCHOR).weekday() != 0:
        raise ValueError("ANCHOR_MUST_BE_MONDAY")
    if len({x["source_uid"] for x in entries}) != 16:
        raise ValueError("DUPLICATE_SOURCE_UID")
    slots, ids = set(), set()
    for entry in entries:
        w,day = int(entry["week"]), int(entry["weekday"])
        source = canonical.get(entry["source_uid"])
        if not (1 <= w <= 8 and day in (3,5) and source):
            raise ValueError("INVALID_WEEK_DAY_OR_SOURCE")
        if (w,day) in slots:
            raise ValueError("DUPLICATE_SLOT")
        slots.add((w,day))
        if str(entry["native_item_id"]) != str(source["provider_item_id"]):
            raise ValueError("SOURCE_ID_CHANGED")
        if entry["title"] != source["title"] or entry["planned_duration_seconds"] != source["planned_duration_seconds"]:
            raise ValueError("SOURCE_PRESCRIPTION_CHANGED")
        if "WINTER" in entry["title"] or "IRONMAN" in entry["title"] or "W01" in entry["title"]:
            raise ValueError("SOURCE_TITLE_NOT_REUSABLE")
        ids.add(str(entry["native_item_id"]))
    if slots != {(w,d) for w in range(1,9) for d in (3,5)} or len(ids)!=16:
        raise ValueError("MISSING_SLOTS")
    if sum(x["planned_duration_seconds"] for x in entries) != p.get("planned_strength_total_seconds") or p["planned_strength_total_seconds"]!=50700:
        raise ValueError("TOTAL_DURATION_DRIFT")
    if len(p.get("plan_description") or "") < 60:
        raise ValueError("BAD_DESCRIPTION")
    return p, entries

def slot_date(e):
    return (date.fromisoformat(ANCHOR)+timedelta(weeks=int(e["week"])-1,days=int(e["weekday"])-1)).isoformat()

def semantic(workout):
    """Dose fingerprint without provider-generated UUIDs or context-specific dates."""
    result=[]
    for block in workout.get("blocks") or []:
        sets=[]
        for pr in block.get("prescriptions") or []:
            rows=[]
            for st in pr.get("sets") or []:
                rows.append(tuple(sorted((str(v.get("parameter")),str(v.get("prescribedValue")))
                                         for v in st.get("parameterValues") or [])))
            sets.append((str((pr.get("exercise") or {}).get("id")),
                         pr.get("coachNotes") or "",tuple(rows)))
        result.append((block.get("blockType"),block.get("title"),
                       block.get("coachNotes") or "",tuple(sets)))
    return (
        workout.get("workoutType"),workout.get("instructions"),
        workout.get("prescribedDurationInSeconds"),tuple(result)
    )

def is_valid_plan(detail, plan_id):
    return (
        isinstance(detail,dict)
        and detail.get("planId") == plan_id
        and detail.get("ownerPersonId") == OWNER
        and detail.get("title") == TITLE
        and detail.get("isPublic") is False
        and detail.get("price") in (None,0)
        and isinstance(detail.get("planPersonId"),int)
        and detail.get("planPersonId") > 0
    )

def prepare(source, entry, plan_person):
    w = copy.deepcopy(source)
    w["id"] = str(uuid.uuid4())
    w["calendarId"] = plan_person
    w["prescribedDate"] = slot_date(entry)
    w["title"] = entry["title"]
    w["prescribedDurationInSeconds"] = int(entry["planned_duration_seconds"])
    # Replace all document UUIDs, not native catalogue exercise IDs.
    for block in w.get("blocks") or []:
        block["id"] = str(uuid.uuid4())
        for pr in block.get("prescriptions") or []:
            pr["id"] = str(uuid.uuid4())
            for st in pr.get("sets") or []:
                st["id"] = str(uuid.uuid4())
                for pv in st.get("parameterValues") or []:
                    pv["id"] = str(uuid.uuid4())
                    pv["executedValue"] = None
    return w

async def main():
    try:
        config,entries=load_manifest()
    except (OSError,ValueError,KeyError,TypeError) as exc:
        emit(stage="STOP_SOURCE",error=str(exc)[:190],provider_writes=0)
        return 2
    emit(stage="PREFLIGHT",title=TITLE,planned_strength_workouts=16,
         duration_min=845,private=True,athletes=0,provider_writes=0)
    async with TPClient() as client:
        owner=await client._get_user_data()
        if not isinstance(owner,dict) or owner.get("personId")!=OWNER:
            emit(stage="STOP_OWNER",writes=0);return 2
        libs=await client.get("/exerciselibrary/v2/libraries")
        if libs.is_error or not isinstance(libs.data,list) or len([
            z for z in libs.data if z.get("exerciseLibraryId")==LIBRARY_ID
            and z.get("libraryName")==LIBRARY_NAME and z.get("ownerId")==OWNER
        ])!=1:
            emit(stage="STOP_LIBRARY_IDENTITY",writes=0);return 2
        _,token,error=await _access(client)
        if error or not token:
            emit(stage="STOP_NATIVE_AUTH",writes=0);return 2
        async with httpx.AsyncClient(timeout=22,follow_redirects=False) as http:
            headers=_headers(token)
            try:
                source_response=await http.get(STRENGTH_API_BASE+NATIVE_LIB_PATH,headers=headers)
            except httpx.RequestError:
                emit(stage="STOP_NATIVE_LIB_CONNECTION",writes=0);return 3
            if source_response.status_code!=200:
                emit(stage="STOP_SOURCE_LIBRARY_HTTP",status=source_response.status_code,writes=0);return 3
            data=source_response.json()
            native=data if isinstance(data,list) else data.get("data") or []
            native_by_id={str(z.get("id")):z for z in native}
            if (len(native)<35 or len(native_by_id)!=len(native)
                or len(set(str(z.get("title")) for z in native))!=len(native)):
                emit(stage="STOP_NATIVE_INVENTORY",found=len(native),writes=0);return 3
            for e in entries:
                item=native_by_id.get(str(e["native_item_id"]))
                workout=(item or {}).get("workout") or {}
                if not (item and item.get("title")==e["title"]
                    and item.get("workoutLibraryItemType")=="ActivityWorkoutTemplate"
                    and workout.get("workoutType")=="StructuredStrength"
                    and workout.get("calendarId") is None and workout.get("prescribedDate") is None
                    and workout.get("prescribedDurationInSeconds")==e["planned_duration_seconds"]
                    and len(workout.get("blocks") or [])>=5):
                    emit(stage="STOP_SOURCE_DRIFT",id=e["native_item_id"],writes=0);return 3
            plans=await client.get("/plans/v1/plans")
            if plans.is_error or not isinstance(plans.data,list):
                emit(stage="STOP_PLAN_INVENTORY",writes=0);return 3
            matches=[x for x in plans.data if (x.get("title") or "").strip()==TITLE]
            if len(matches)>1:
                emit(stage="STOP_DUPLICATE_PLAN_TITLE",count=len(matches),writes=0);return 4
            created=False
            plan_id=None
            if not matches:
                payload={
                    "title":TITLE,
                    "startDate":ANCHOR+"T00:00:00",
                    "weekCount":8,"dayCount":56,"isPublic":False,
                    "description":config["plan_description"]
                }
                try:
                    response=await client._request(
                        "POST","/plans/v1/plans",json=payload,_retry_on_401=False
                    )
                except Exception as exc:
                    emit(stage="STOP_CREATE_AMBIGUOUS",kind=type(exc).__name__,retry=False)
                    return 5
                # Reconcile an uncertain response from the provider; NEVER repeat.
                plans=await client.get("/plans/v1/plans")
                if plans.is_error or not isinstance(plans.data,list):
                    emit(stage="STOP_CREATE_UNVERIFIABLE",retry=False)
                    return 5
                matches=[x for x in plans.data if (x.get("title") or "").strip()==TITLE]
                if len(matches)!=1 or not matches[0].get("planId"):
                    emit(stage="STOP_CREATE_MISSING_OR_COLLISION",count=len(matches),
                         provider_error=str(response.error_code) if response.is_error else None,
                         retry=False)
                    return 5
                created=True
            plan_id=matches[0].get("planId")
            detail=await client.get(f"/plans/v1/plans/{plan_id}")
            if detail.is_error or not is_valid_plan(detail.data,plan_id):
                emit(stage="STOP_PLAN_DETAIL",plan_id=plan_id,created=created,
                     keys=sorted(detail.data.keys()) if isinstance(detail.data,dict) else [],
                     retry=False);return 5
            plan_person=detail.data["planPersonId"]
            if detail.data.get("workoutCount") not in (None,0) and created:
                emit(stage="STOP_NEW_PLAN_UNEXPECTED_ITEMS",plan_id=plan_id,
                     count=detail.data.get("workoutCount"));return 5
            if created:
                emit(stage="PLAN_CREATED_AND_PRIVATE_VERIFIED",plan_id=plan_id,
                     plan_person=plan_person,owner=OWNER,
                     provider_reported_weeks=detail.data.get("weekCount"))
            else:
                emit(stage="EXISTING_TARGET_RECONCILE",plan_id=plan_id,
                     existing_workouts=detail.data.get("workoutCount"))
            final_day=(date.fromisoformat(ANCHOR)+timedelta(weeks=8)).isoformat()
            # Native reads use the PlanPerson calendar, NEVER an athlete calendar.
            async def native_read():
                rr=await http.get(STRENGTH_API_BASE+
                    f"/rx/activity/v1/workouts/calendar/{plan_person}/{ANCHOR}/{final_day}",
                    headers=headers)
                if rr.status_code!=200:raise ValueError("NATIVE_PLAN_CALENDAR_HTTP_"+str(rr.status_code))
                x=rr.json()
                if isinstance(x,dict):
                    x=x.get("data")
                if not isinstance(x,list):raise ValueError("NATIVE_PLAN_SHAPE")
                return x
            try:
                existing=await native_read()
            except (ValueError,httpx.RequestError) as exc:
                emit(stage="STOP_PLAN_NATIVE_READ",plan_id=plan_id,reason=str(exc)[:140]);return 6
            valid_keys={(slot_date(e),e["title"]) for e in entries}
            seen={}
            for z in existing:
                key=((z.get("prescribedDate") or "")[:10],z.get("title"))
                if key in seen or key not in valid_keys:
                    emit(stage="STOP_UNEXPECTED_NATIVE",plan_id=plan_id,key=key,
                         native_count=len(existing));return 6
                seen[key]=z
            if detail.data.get("workoutCount") not in (None,len(existing)):
                emit(stage="STOP_OTHER_WORKOUTS_OR_DRIFT",plan_id=plan_id,
                     declared_count=detail.data.get("workoutCount"),
                     native_found=len(existing));return 6
            # Verify currently existing instances (for recovery after partial POST).
            for entry in entries:
                key=(slot_date(entry),entry["title"])
                if key in seen:
                    source=native_by_id[str(entry["native_item_id"])]["workout"]
                    full=await http.get(STRENGTH_API_BASE+
                        f"/rx/activity/v1/workouts/{seen[key]['id']}",headers=headers)
                    w=(full.json().get("data") or {}) if full.status_code==200 else {}
                    if (w.get("calendarId")!=plan_person or w.get("title")!=entry["title"] or
                        (w.get("prescribedDate") or "")[:10]!=slot_date(entry) or
                        semantic(w)!=semantic(source)):
                        emit(stage="STOP_EXISTING_INSTANCE_DRIFT",plan_id=plan_id,key=key)
                        return 6
            added=0
            for entry in entries:
                key=(slot_date(entry),entry["title"])
                if key in seen:
                    emit(stage="SKIP_ALREADY_NATIVE_VERIFIED",week=entry["week"],
                         weekday=entry["weekday"],item=entry["native_item_id"])
                    continue
                source=native_by_id[str(entry["native_item_id"])]["workout"]
                prepared=prepare(source,entry,plan_person)
                if semantic(prepared)!=semantic(source):
                    emit(stage="STOP_LOCAL_CLONE_DIFF",plan_id=plan_id,source=entry["native_item_id"])
                    return 7
                try:
                    written=await http.post(STRENGTH_API_BASE+
                        f"/rx/activity/v1/plans/{plan_id}/workouts/save",
                        json=prepared,headers=headers)
                except httpx.RequestError:
                    emit(stage="STOP_NATIVE_POST_AMBIGUOUS",plan_id=plan_id,
                         week=entry["week"],weekday=entry["weekday"],
                         count_added=added,retry=False)
                    return 8
                if written.status_code!=200:
                    # Always inspect real state before considering any future recovery;
                    # an error response is NOT permission to retry this POST.
                    emit(stage="STOP_NATIVE_POST_REJECTED",plan_id=plan_id,
                         http=written.status_code,week=entry["week"],
                         weekday=entry["weekday"],added=added,retry=False)
                    return 8
                provider_data=written.json().get("data") or {}
                workout_id=str(provider_data.get("id") or prepared["id"])
                read=await http.get(STRENGTH_API_BASE+
                    f"/rx/activity/v1/workouts/{workout_id}",headers=headers)
                actual=(read.json().get("data") or {}) if read.status_code==200 else {}
                if (actual.get("calendarId")!=plan_person or
                    actual.get("title")!=entry["title"] or
                    (actual.get("prescribedDate") or "")[:10]!=slot_date(entry) or
                    semantic(actual)!=semantic(source)):
                    emit(stage="STOP_INSTANCE_READBACK",plan_id=plan_id,week=entry["week"],
                         weekday=entry["weekday"],native_workout_id=workout_id,
                         added=added,retry=False)
                    return 9
                added+=1
                emit(stage="NATIVE_INSTANCE_VERIFIED",plan_id=plan_id,week=entry["week"],
                     weekday=entry["weekday"],source_id=entry["native_item_id"],
                     workout_id=workout_id,
                     duration_sec=entry["planned_duration_seconds"])
            # Final inventory: only the 16 required strength occurrences, no duplicates.
            try:
                after=await native_read()
            except (ValueError,httpx.RequestError):
                emit(stage="STOP_FINAL_NATIVE_INVENTORY",plan_id=plan_id,added=added)
                return 10
            mapping={(slot_date(x),x["title"]):x for x in entries}
            keys=[((x.get("prescribedDate") or "")[:10],x.get("title")) for x in after]
            if len(after)!=16 or len(set(keys))!=16 or set(keys)!=set(mapping):
                emit(stage="STOP_FINAL_MAPPING",plan_id=plan_id,native=len(after),
                     unique=len(set(keys)),added=added)
                return 10
            for x in after:
                key=((x.get("prescribedDate") or "")[:10],x.get("title"))
                item=mapping[key]
                full=await http.get(STRENGTH_API_BASE+
                     f"/rx/activity/v1/workouts/{x['id']}",headers=headers)
                workout=(full.json().get("data") or {}) if full.status_code==200 else {}
                source=native_by_id[str(item["native_item_id"])]["workout"]
                if workout.get("calendarId")!=plan_person or semantic(workout)!=semantic(source):
                    emit(stage="STOP_FINAL_SEMANTIC",plan_id=plan_id,week=item["week"],
                         weekday=item["weekday"])
                    return 11
            detail=await client.get(f"/plans/v1/plans/{plan_id}")
            if (detail.is_error or not is_valid_plan(detail.data,plan_id)
                or detail.data.get("workoutCount")!=16
                or detail.data.get("weekCount")!=8):
                emit(stage="STOP_FINAL_PLAN_SUMMARY",plan_id=plan_id,
                     workout_count=detail.data.get("workoutCount") if not detail.is_error else None,
                     week_count=detail.data.get("weekCount") if not detail.is_error else None,
                     verified_native=16,added=added)
                return 12
            emit(stage="WINTER8_NATIVE_STRENGTH_PLAN_VERIFIED",plan_id=plan_id,
                 owner=OWNER,plan_person=plan_person,private=True,price=None,
                 weeks=8,strength_native=16,planned_minutes=845,
                 newly_inserted=added,existing_verified=16-added,
                 source_library=LIBRARY_ID,
                 athlete_calendar_writes=0,marketplace_writes=0)
            return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
