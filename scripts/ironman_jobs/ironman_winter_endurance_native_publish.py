"""Publish WINTER 8W SW/BI/RU native Builder templates and plan occurrences.

Scoped to coach-owned 3 shared libraries and already-private plan 689369.
Translates canonical manifest with the same swim recovery compiler and native
preview function already proven on CHASING. Strict duplicate prevention;
golden-first 1 SW + 1 BI + 1 RU; up to 14 provider writes per invocation.
No athlete calendar, no strength modifications, no new plan.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections import Counter
from datetime import date,timedelta
from pathlib import Path

from tp_mcp.client import TPClient
from tp_mcp.tools.library import _ensure_structure_preview
from scripts.ironman_jobs.chasing_swim_rebuild_20261018 import (
    _group as swimming_group,
    structure_for as swimming_builder,
    audit_native_swim_rests as audit_swimming,
)

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/"data/ironman_winter_8w_endurance_native.json"
OWNER=2116886
PLAN=689369
PERSON=6709024
TITLE="ALBERTO FAZI ENDURANCE | WINTER FOUNDATION | 8 settimane | Italiano"
ANCHOR=date(2027,1,4)
LIB={"SW":3891872,"BI":3892601,"RU":3892602}
SPORT={"SW":1,"BI":2,"RU":3}
SUBTYPE={"SW":2,"BI":3,"RU":10}
LIBNAMES={"SW":"ALBERTO FAZI ENDURANCE | Nuoto | IT",
          "BI":"ALBERTO FAZI ENDURANCE | Bici | IT",
          "RU":"ALBERTO FAZI ENDURANCE | Corsa | IT"}
MAX_WRITES=14

def emit(**v):
    print(json.dumps(v,ensure_ascii=False,default=str),flush=True)

def must(ok,reason):
    if not ok: raise ValueError(reason)

def source():
    cfg=json.loads(DATA.read_text(encoding="utf-8"))
    must(cfg.get("schema")=="IRONMAN_WINTER_8W_ENDURANCE_NATIVE_V1","BAD_SCHEMA")
    must(cfg.get("provider_plan_id")==PLAN and cfg.get("provider_plan_person_id")==PERSON,"BAD_PLAN")
    must(cfg.get("owner_id")==OWNER and cfg.get("plan_title")==TITLE,"BAD_OWNER_OR_TITLE")
    must(cfg.get("anchor")==ANCHOR.isoformat() and cfg.get("libraries")==LIB,"BAD_CALENDAR_OR_LIBRARIES")
    items=cfg.get("workouts") or []
    must(len(items)==58 and len({e["uid"] for e in items})==58,"EXPECTED_58_UNIQUE")
    must(Counter(e["sport"] for e in items)==Counter({"SW":16,"BI":20,"RU":22}),"SPORT_COUNTS")
    must(sum(e["minutes"] for e in items)==3250 and sum(e.get("metres",0) for e in items)==34600,"TOTALS")
    must(len({(e["week"],e["weekday"],e["sport"]) for e in items})==58,"DUPLICATE_SLOTS")
    must(len({(e["sport"],e["title"]) for e in items})==51,"UNIQUE_TEMPLATES_EXPECTED_51")
    must(all(e["title"].count("|")==1 and "WINTER" not in e["title"] and "W01" not in e["title"]
             and e["minutes"]>0 and 1<=e["week"]<=8 for e in items),"TITLE_OR_MINUTES")
    weekly=[sum(e["minutes"] for e in items if e["week"]==w) for w in range(1,9)]
    must(weekly==[280,315,400,320,455,505,540,435],"WEEKLY_ENDURANCE_BUDGET")
    must([k for k in cfg["policy"] if k in ("BI","RU","SW")]==["BI","RU","SW"],"METRIC_CONTRACT")
    items.sort(key=lambda z:(z["week"],z["weekday"],SPORT[z["sport"]]))
    return cfg,items

def dt(e):
    return (ANCHOR+timedelta(weeks=e["week"]-1,days=e["weekday"]-1)).isoformat()

def timeblock(name,kind,minutes,lo,hi):
    return {"name":name,"length":{"value":int(minutes*60),"unit":"second"},
            "targets":[{"minValue":lo,"maxValue":hi}],
            "intensityClass":kind,"openDuration":False}

def finish_duration(blocks,metric):
    secs=0
    for b in blocks:
        reps=b["length"]["value"] if b["type"]=="repetition" else 1
        length=sum(q["length"]["value"] for q in b["steps"])*reps
        b["begin"]=secs;b["end"]=secs+length;secs+=length
    data={"structure":blocks,"primaryLengthMetric":"duration",
          "primaryIntensityMetric":metric,"primaryIntensityTargetOrRange":"range"}
    result=_ensure_structure_preview(data)
    must(bool(result.get("polyline")),"MISSING_GRAPH")
    must(blocks[-1]["end"]==secs,"BLOCK_TIME_END")
    return result,secs

def bike_builder(e):
    parts=e["blocks"]
    result=[]
    def add(steps,reps=1):
        result.append({"type":"repetition" if reps>1 else "step",
          "length":{"value":reps,"unit":"repetition"},"steps":steps})
    def block(kind,minutes):
        d={
           "warm":("Avvio facile 50-60% FTP","warmUp",50,60),
           "cool":("Defaticamento 45-55% FTP","coolDown",45,55),
           "endurance":("Fondo aerobico 60-70% FTP","active",60,70),
           "easy":("Pedalata fluida 55-65% FTP","active",55,65),
           "cadence":("Agilita naturale controllata 55-65% FTP","active",55,65),
           "steady":("Steady aerobico basso 70-75% FTP","active",70,75),
           "rest":("Recupero facile 55-65% FTP","rest",55,65)
        }
        name,klass,lo,hi=d[kind]
        return timeblock(name,klass,minutes,lo,hi)
    if any(z[0]=="cadence" for z in parts):
        must([z[0] for z in parts]==["warm","cadence","easy","endurance","cool"],"BAD_CADENCE_BLOCKS")
        add([block("warm",parts[0][1])])
        must(parts[1][2]==parts[2][2]==6,"BAD_CADENCE_REPETITION")
        add([block("cadence",parts[1][1]),block("easy",parts[2][1])],6)
        add([block("endurance",parts[3][1])]);add([block("cool",parts[4][1])])
    elif any(z[0]=="steady" for z in parts):
        must([z[0] for z in parts]==["warm","steady","rest","endurance","cool"],"BAD_STEADY_BLOCKS")
        must(parts[1][2]==3 and parts[2][2]==2,"BAD_STEADY_RECOVERY")
        add([block("warm",parts[0][1])])
        add([block("steady",parts[1][1]),block("rest",parts[2][1])],2)
        add([block("steady",parts[1][1])])
        add([block("endurance",parts[3][1])]);add([block("cool",parts[4][1])])
    else:
        must(len(parts)==3,"BAD_ENDURANCE_PARTS")
        for kind,minutes in parts:add([block(kind,minutes)])
    result,secs=finish_duration(result,"percentOfFtp")
    must(secs==e["minutes"]*60,"BIKE_SECONDS_DIFFER_FROM_MANIFEST")
    return result

def run_builder(e):
    result=[]
    easy=(80,86) if e["weekday"]==7 else (78,84)
    for kind,minutes in e["blocks"]:
        if kind=="warm":label,k,vals="Avvio facile e mobilita","warmUp",(76,82)
        elif kind=="cool":label,k,vals="Defaticamento sciolto","coolDown",(70,78)
        elif kind=="drills":label,k,vals="Tecnica PAM/drill incluse camminate e pause","active",(70,78)
        else:label,k,vals="Corsa endurance facile","active",easy
        result.append({"type":"step","length":{"value":1,"unit":"repetition"},
                       "steps":[timeblock(label,k,minutes,*vals)]})
    result,seconds=finish_duration(result,"percentOfThresholdPace")
    must(seconds==e["minutes"]*60,"RUN_SECONDS_DIFFER_FROM_MANIFEST")
    return result

def swim_builder(e):
    parts=e["groups"]
    native=[]
    for ix,g in enumerate(parts):
        klass=("warmUp" if ix==0 else "coolDown" if "Defaticamento" in g["label"] else "active")
        z=swimming_group(g["count"],g["distance"],g["label"],tuple(g["rpe"]),klass,g["rest"])
        native.append(z)
    s=swimming_builder(native)
    qa=audit_swimming(native,s)
    must(qa["native_metres"]==e["metres"],"SWIMMING_METRES")
    must(s["primaryIntensityMetric"]=="rpe" and s["primaryLengthMetric"]=="distance","SWIM_METRIC")
    must(all(bool(step["targets"]) for block in s["structure"] for step in block["steps"]),"SWIM_TARGET_MISSING")
    return s

def description(e):
    sport=e["sport"]
    head=("NUOTO" if sport=="SW" else "BICI" if sport=="BI" else "CORSA")
    dose=(f"{e['metres']} m distance-based; {e['minutes']} min indicativi con pause comprese"
          if sport=="SW" else f"{e['minutes']} min inclusi warmup e cooldown")
    primary=("Nuoto: Builder metri + RPE, nessuna CSS obbligatoria senza baseline valida."
             if sport=="SW" else
             "Bici: Builder percentOfFtp primario con FTP testata e aggiornata, RPE secondaria 2-3, steady RPE 4. Non confondere %FTP con LT1; ridurre il target se la risposta fisiologica non e coerente."
             if sport=="BI" else
             "Corsa: Builder % velocita soglia corsa solo con threshold pace affidabile; RPE 2-3, corsa conversazionale. Se threshold non valido, il coach individualizza prima di applicare il piano.")
    return (
        f"OBIETTIVO {head}\n{e['aim']}\n\n"
        f"STRUTTURA E DURATA\n{dose}. Seguire integralmente la struttura nativa TrainingPeaks, compresi i recuperi. "
        f"Il minutaggio non giustifica la riduzione forzata dei recuperi.\n\n"
        f"TARGET E AUTOREGOLAZIONE\n{primary}\n\n"
        f"TECNICA E INDICAZIONI\n{e['cues']}\n\n"
        "COSA OSSERVARE\nRespirazione, controllo tecnico, stabilita del gesto e recupero il giorno seguente. "
        "Non aggiungere lavori di soglia, gare o volume imprevisto. "
        "In caso di dolore che altera il movimento, interrompere e rivalutare.\n\n"
        f"FUELING E IDRATAZIONE\n{e['fueling']}"
    )

def compiled(e):
    s=(swim_builder(e) if e["sport"]=="SW" else bike_builder(e) if e["sport"]=="BI"
       else run_builder(e))
    if e["sport"]!="SW":
        must(s["primaryLengthMetric"]=="duration","DURATION_METRIC")
        for b in s["structure"]:
            for t in b["steps"]:
                must(t.get("targets") and t["targets"][0]["maxValue"]>0,"ACTIVE_NO_TARGET")
    must(bool(s.get("polyline")) and len(s["polyline"])>=4,"NO_POLYLINE")
    return {
        "exerciseLibraryId":LIB[e["sport"]],"itemName":e["title"],
        "workoutTypeId":SPORT[e["sport"]],"workoutSubTypeId":SUBTYPE[e["sport"]],
        "totalTimePlanned":e["minutes"]/60,
        "distancePlanned":e.get("metres") if e["sport"]=="SW" else None,
        "description":description(e),
        "structure":s
    }

def source_equal(actual,expected):
    for k in ("itemName","workoutTypeId","workoutSubTypeId","description"):
        if actual.get(k)!=expected.get(k):return False
    if abs((actual.get("totalTimePlanned") or 0)-(expected.get("totalTimePlanned") or 0))>0.00002:
        return False
    if expected["workoutTypeId"]==1 and actual.get("distancePlanned")!=expected["distancePlanned"]:
        return False
    s=actual.get("structure") or {}
    t=expected["structure"]
    if (s.get("primaryLengthMetric")!=t.get("primaryLengthMetric") or
        s.get("primaryIntensityMetric")!=t.get("primaryIntensityMetric")
        or s.get("primaryIntensityTargetOrRange")!=t.get("primaryIntensityTargetOrRange")
        or not s.get("polyline")):return False
    # Compare complete native dose excluding representation-only polyline.
    return s.get("structure")==t.get("structure")

def plan_equal(actual,expected,target):
    s=actual.get("structure") or {}
    return (
        (actual.get("workoutDay") or "")[:10]==target
        and actual.get("title")==expected["itemName"]
        and actual.get("workoutTypeValueId")==expected["workoutTypeId"]
        and actual.get("description")==expected["description"]
        and abs((actual.get("totalTimePlanned") or 0)-expected["totalTimePlanned"])<0.00002
        and (expected["workoutTypeId"]!=1 or
             actual.get("distancePlanned")==expected["distancePlanned"])
        and s.get("primaryLengthMetric")==expected["structure"]["primaryLengthMetric"]
        and s.get("primaryIntensityMetric")==expected["structure"]["primaryIntensityMetric"]
        and s.get("structure")==expected["structure"]["structure"]
        and bool(s.get("polyline"))
    )

def is_golden_preflight(items):
    first={}
    for x in items:
        if x["week"]==1 and x["sport"] in ("SW","BI","RU"):
            first.setdefault(x["sport"],x)
    must(len(first)==3,"MISSING_GOLDEN")
    for sport in first:
        v=compiled(first[sport])
        must(v["structure"]["primaryIntensityMetric"]=={"SW":"rpe","BI":"percentOfFtp","RU":"percentOfThresholdPace"}[sport],"GOLDEN_TARGET")
    return first

async def main():
    try:
        cfg,items=source()
        compiled_map={}
        for e in items:
            k=(e["sport"],e["title"])
            candidate=compiled(e)
            if k in compiled_map:
                must(compiled_map[k]==candidate,"SAME_TITLE_DIFFERENT_NATIVE_DOSE:"+str(k))
            compiled_map[k]=candidate
        first=is_golden_preflight(items)
        must(len(compiled_map)==51,"COMPILED_TEMPLATE_COUNT")
    except Exception as exc:
        emit(stage="STOP_OFFLINE_PREFLIGHT",reason=str(exc)[:230],provider_writes=0)
        return 2
    emit(stage="SOURCE_QA_PASS",manifest_items=58,templates_unique=51,
         metres=34600,planned_min=3250,prototype_sports=list(first),
         planned_total_with_strength_min=4095,provider_writes=0)
    async with TPClient() as client:
        me=await client._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"STOP_COACH")
        pl=await client.get(f"/plans/v1/plans/{PLAN}")
        must(not pl.is_error and isinstance(pl.data,dict),"PLAN_NOT_READ")
        p=pl.data
        must(p.get("planId")==PLAN and p.get("planPersonId")==PERSON and
             p.get("ownerPersonId")==OWNER and p.get("title")==TITLE and
             p.get("isPublic") is False and p.get("price") in (None,0),"WRONG_PRIVATE_PLAN")
        must(16<=p.get("workoutCount",0)<=74,"PLAN_COUNT_OUT_OF_RANGE")
        libs=await client.get("/exerciselibrary/v2/libraries")
        must(not libs.is_error and isinstance(libs.data,list),"LIBRARY_LIST_NOT_READ")
        for sp,lid in LIB.items():
            must(len([x for x in libs.data if x.get("exerciseLibraryId")==lid and
                     x.get("ownerId")==OWNER and x.get("libraryName")==LIBNAMES[sp]])==1,
                     "WRONG_LIBRARY_"+sp)
        original_strength=16
        start=ANCHOR.isoformat()
        end=(ANCHOR+timedelta(weeks=8)).isoformat()
        async def classic_read():
            r=await client.get(f"/plans/v1/plans/{PLAN}/workouts/{start}/{end}")
            must(not r.is_error and isinstance(r.data,list),"PLAN_CLASSIC_READ")
            return r.data
        existing=await classic_read()
        expected={(dt(e),e["sport"],e["title"]) for e in items}
        unique=set()
        for z in existing:
            sport={1:"SW",2:"BI",3:"RU"}.get(z.get("workoutTypeValueId"))
            key=((z.get("workoutDay") or "")[:10],sport,z.get("title"))
            must(sport and key in expected and key not in unique,"UNEXPECTED_OR_DUPLICATED_EXISTING_CLASSIC")
            unique.add(key)
        must(len(existing)==p.get("workoutCount")-original_strength,
             "PLAN_EXISTING_STRENGTH_OR_CLASSIC_DRIFT")
        by_library={}
        for s,lid in LIB.items():
            get=await client.get(f"/exerciselibrary/v2/libraries/{lid}/items")
            must(not get.is_error and isinstance(get.data,list),"LIBRARY_READ_"+s)
            by_library[s]=get.data
        # First 3 instances must all be exact before the rest can be published.
        golden_keys={(dt(first[s]),s,first[s]["title"]) for s in first}
        done_golden=set()
        writes=0
        inserted=0
        templates_created=0
        for i,e in enumerate(items):
            sp=e["sport"];key=(sp,e["title"]);target=dt(e)
            item=compiled_map[key]
            name=item["itemName"]
            matching=[x for x in by_library[sp] if x.get("itemName")==name]
            must(len(matching)<=1,"DUPLICATE_LIBRARY_TITLE:"+name)
            if matching:
                must(source_equal(matching[0],item),"LIBRARY_COLLISION_WRONG_DOSE:"+name)
                item_id=matching[0]["exerciseLibraryItemId"]
            else:
                if writes>=MAX_WRITES:
                    emit(stage="BATCH_LIMIT_REACHED",writes=writes,library_created=templates_created,
                         plan_inserted=inserted,last_uid=items[i-1]["uid"] if i else None,
                         remaining_manifest=58-i,plan_id=PLAN)
                    return 0
                payload={k:v for k,v in item.items() if v is not None}
                try:
                    res=await client._request("POST",f"/exerciselibrary/v1/libraries/{LIB[sp]}/items",
                                              json=payload,_retry_on_401=False)
                except Exception as exc:
                    emit(stage="STOP_LIBRARY_POST_UNKNOWN",uid=e["uid"],kind=type(exc).__name__,
                         writes=writes,retry=False);return 5
                writes+=1
                get=await client.get(f"/exerciselibrary/v2/libraries/{LIB[sp]}/items")
                must(not get.is_error and isinstance(get.data,list),"LIBRARY_POST_READBACK_UNAVAILABLE")
                by_library[sp]=get.data
                found=[x for x in get.data if x.get("itemName")==name]
                if len(found)!=1 or not source_equal(found[0],item):
                    emit(stage="STOP_LIBRARY_NOT_VERIFIED",uid=e["uid"],provider_error=res.is_error,
                         count=len(found),writes=writes,retry=False)
                    return 5
                item_id=found[0]["exerciseLibraryItemId"]
                must(not res.is_error,"LIBRARY_POST_REPORTED_ERROR_AFTER_READBACK")
                templates_created+=1
                emit(stage="LIBRARY_TEMPLATE_VERIFIED",sport=sp,id=item_id,title=name,uid=e["uid"])
            match=[z for z in existing if (z.get("workoutDay") or "")[:10]==target and
                     z.get("workoutTypeValueId")==SPORT[sp] and z.get("title")==name]
            must(len(match)<=1,"PLAN_DUPLICATE_MATCH")
            if match:
                must(plan_equal(match[0],item,target),"PLAN_EXISTING_WRONG_NATIVE_CONTENT")
                if (target,sp,name) in golden_keys:done_golden.add(sp)
                continue
            # Golden-first blocks all later writes until SW+BI+RU passed.
            if e["week"]>1 or (e["week"]==1 and e["weekday"]>3):
                must(done_golden=={"SW","BI","RU"},"GOLDEN_GATE_INCOMPLETE")
            if writes>=MAX_WRITES:
                emit(stage="BATCH_LIMIT_REACHED",writes=writes,library_created=templates_created,
                     plan_inserted=inserted,remaining_manifest=58-i,plan_id=PLAN)
                return 0
            before_count=original_strength+len(existing)
            post_body={"planId":PLAN,"exerciseLibraryItemId":item_id,"workoutDateTime":target}
            try:
                result=await client._request("POST",
                    f"/plans/v1/plans/{PLAN}/commands/addworkoutfromlibraryitem",
                    json=post_body,_retry_on_401=False)
            except Exception as exc:
                emit(stage="STOP_PLAN_POST_UNKNOWN",uid=e["uid"],kind=type(exc).__name__,
                     writes=writes,retry=False);return 6
            writes+=1
            rr=await classic_read()
            actual=[z for z in rr if (z.get("workoutDay") or "")[:10]==target
                    and z.get("workoutTypeValueId")==SPORT[sp] and z.get("title")==name]
            if len(actual)!=1 or not plan_equal(actual[0],item,target) or len(rr)!=len(existing)+1:
                emit(stage="STOP_PLAN_WRITE_READBACK",uid=e["uid"],is_error=result.is_error,
                     found=len(actual),count_before=len(existing),count_after=len(rr),
                     writes=writes,retry=False);return 6
            # Provider final summary also must count 16 native Strength items still.
            meta=await client.get(f"/plans/v1/plans/{PLAN}")
            if meta.is_error or meta.data.get("workoutCount")!=before_count+1 or meta.data.get("isPublic") is not False:
                emit(stage="STOP_PLAN_SUMMARY_READBACK",uid=e["uid"],before_count=before_count,
                     plan_count=None if meta.is_error else meta.data.get("workoutCount"),
                     writes=writes);return 6
            must(not result.is_error,"POST_REPORTED_ERROR_BUT_INSTANCE_PRESENT")
            existing=rr
            inserted+=1
            if (target,sp,name) in golden_keys:done_golden.add(sp)
            emit(stage="PLAN_WORKOUT_VERIFIED",uid=e["uid"],week=e["week"],day=e["weekday"],
                 sport=sp,item_id=item_id,plan_workout_id=actual[0].get("workoutId"),
                 planned_minutes=e["minutes"],metres=e.get("metres",0),
                 metric=item["structure"]["primaryIntensityMetric"])
        must(done_golden=={"SW","BI","RU"},"GOLDEN_NOT_PASSED")
        final=await classic_read()
        must(len(final)==58,"FINAL_ENDURANCE_58")
        final_meta=await client.get(f"/plans/v1/plans/{PLAN}")
        must(not final_meta.is_error and final_meta.data.get("workoutCount")==74
             and final_meta.data.get("isPublic") is False and
             final_meta.data.get("weekCount")==8,"FINAL_PLAN_74_PRIVATE_8W")
        for x in items:
            k=(dt(x),x["sport"],x["title"])
            matches=[w for w in final if ((w.get("workoutDay") or "")[:10],
               {1:"SW",2:"BI",3:"RU"}.get(w.get("workoutTypeValueId")),w.get("title"))==k]
            must(len(matches)==1 and plan_equal(matches[0],compiled_map[(x["sport"],x["title"])],dt(x)),
                 "FINAL_WORKOUT_SEMANTIC_FAIL:"+x["uid"])
        emit(stage="WINTER8_NATIVE_ENDURANCE_FULLY_VERIFIED",
             plan_id=PLAN,workouts_total=74,endurance=58,strength_untouched=16,
             swim=16,bike=20,run=22,templates_distinct=51,
             swim_metres=34600,endurance_minutes=3250,strength_minutes=845,
             total_minutes=4095,private=True,
             new_templates_this_call=templates_created,new_instances_this_call=inserted,
             athlete_calendar_writes=0)
        return 0

if __name__=="__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        emit(stage="STOP_EXECUTION",reason=str(exc)[:400],retry_post=False)
        raise
