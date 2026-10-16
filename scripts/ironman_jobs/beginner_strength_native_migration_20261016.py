"""Migrate Beginner 679801 classic text Strength workouts to native StructuredStrength.
36 exact source IDs; live parse of approved text; golden-first native write; verify all native
twins before deleting any classic source. No athlete calendar, no other plan/library writes.
"""
from __future__ import annotations
import asyncio, json, re, copy
from datetime import date, timedelta
from pathlib import Path
import httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import (
    _access, _headers, _build_payload, STRENGTH_API_BASE
)

P=679801
OWNER=2116886
EXPECTED_META_COUNT=225
SOURCE_IDS={
3978611861,3978611904,3978611883,3978611911,3978611902,3978611865,
3978611892,3978611927,3978612069,3978611975,3978611992,3978612084,
3978612013,3978611928,3978612064,3978611980,3978612004,3978611989,
3978611990,3978611991,3978611999,3978611959,3978612071,3978611979,
3978612092,3978611983,3978612073,3978612076,3978612090,3978612133,
3978612027,3978612031,3978612042,3978612100,3978611945,3978611956
}
BACKUP=Path.home()/".trainingpeaks-mcp"/"beginner679801_strength_builder_20261016_before.json"

def need(x,m):
    if not x: raise RuntimeError(m)

def wid(w):
    return int(w.get("workoutId") or w.get("planWorkoutId") or w.get("id") or 0)

def stable(w):
    return {k:v for k,v in w.items() if k!="lastModifiedDate"}

def clean_title(t):
    t=(t or "").strip()
    return t.replace("First Ironman 24W: ","",1) if t.startswith("First Ironman 24W: ") else t

def normalize(s):
    return (s or "").replace("–","-").replace("—","-").replace("’","'").replace("“",'"').replace("”",'"')

def central_lines(desc):
    s=normalize(desc)
    m=re.search(r"PARTE CENTRALE\n(.*?)(?:\n\n(?:INTENSITA|CHIUSURA|RECUPERI|NOTE)\b|\Z)",s,re.S|re.I)
    need(m,"NO_PARTE_CENTRALE")
    return [x.strip(" -") for x in m.group(1).splitlines() if x.strip() and re.match(r"^\d",x.strip())]

def exercise_for(line,title):
    l=line.lower()
    if "single-leg rdl" in l or "single leg rdl" in l:
        return "156","Single Leg Romanian Deadlift","RepsPerSide"
    if "step-up" in l or "step up" in l:
        return "165","Weighted Step Up","RepsPerSide"
    if "affondo indietro" in l:
        return "76","Reverse Lunge","RepsPerSide"
    if "hip thrust" in l or "ponte glutei" in l:
        return "579","Glute Bridge","Reps"
    if "romanian deadlift" in l or "hip hinge" in l:
        return "154","Romanian Deadlift","Reps"
    if "split squat" in l:
        return "158","Split Squat","RepsPerSide"
    if "calf raise" in l or "soleus" in l:
        if "per lato" in l:
            return "554","Elevated Single Leg Body Weight Calf Raise","RepsPerSide"
        return "553","Elevated Body Weight Calf Raise","Reps"
    if "push-up" in l or "push up" in l:
        if "inclinato" in l:
            return "616","Incline Push Up","Reps"
        return "5366","Push Up","Reps"
    if re.search(r"\brow\b",l):
        return "151","Single Arm DB Row","RepsPerSide"
    if "side plank" in l:
        return "79","Side Plank","Duration"
    if "dead bug" in l:
        return "5312","Ipsilateral Dead Bug","RepsPerSide"
    if "core facile" in l or re.search(r"\bplank\b",l):
        return "71","Plank","Duration"
    if "squat" in l:
        # Beginner base/scarico/activation stays equipment-optional.
        if any(x in title.lower() for x in ("base","scarico","attivazione")) or "facile" in l:
            return "1","Air Squat","Reps"
        return "144","Goblet Squat","Reps"
    raise RuntimeError("UNMAPPED_EXERCISE: "+line)

def parse_line(line,title):
    s=normalize(line)
    # 1-2x4, 3x5-8, 2x20-30", etc. Builder uses conservative lower bound;
    # original range remains visible verbatim in exercise notes.
    m=re.match(r"^(\d+)(?:-(\d+))?x(\d+)(?:-(\d+))?(\")?\s+(.*)$",s,re.I)
    need(m,"UNPARSED_LINE: "+line)
    sets_n=int(m.group(1))
    value=int(m.group(3))
    is_seconds=bool(m.group(5))
    eid,ename,param=exercise_for(s,title)
    if param=="Duration":
        if not is_seconds:
            # textual core/plank without seconds is represented as 20 s default.
            value=20
        setval={"RepsPerSide":1,"Duration":value} if eid=="79" else {"Reps":1,"Duration":value}
    else:
        setval={param:value}
    return {
        "type":"SingleExercise",
        "title":ename,
        "exercises":[{
            "id":eid,
            "notes":line + (" | Builder: valore minimo del range; resta valido il range scritto." if (m.group(2) or m.group(4)) else ""),
            "sets":[copy.deepcopy(setval) for _ in range(sets_n)]
        }]
    }

def blocks_for(w):
    title=clean_title(w.get("title"))
    lines=central_lines(w.get("description"))
    need(5 <= len(lines) <= 7,"UNEXPECTED_EXERCISE_COUNT_"+str(wid(w)))
    blocks=[parse_line(x,title) for x in lines]
    return blocks

def instructions_for(w):
    txt=w.get("description") or ""
    return (
      txt +
      "\n\nSTRENGTH BUILDER\n"
      "Gli esercizi, le serie e i video sono ora disponibili anche nei blocchi nativi TrainingPeaks. "
      "Quando la prescrizione originale usa un intervallo (per esempio 5-8 ripetizioni o 1-2 serie), "
      "il Builder mostra il valore minimo come default conservativo: resta valido l'intero intervallo scritto "
      "se tecnica, RPE e recupero lo consentono."
    )

async def classic_all(c,start,end):
    r=await c.get(f"/plans/v1/plans/{P}/workouts/{start}/{end}")
    need(not r.is_error and isinstance(r.data,list),"CLASSIC_READ")
    return r.data

async def native_all(h,access,start,end):
    r=await h.get(f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{P}/workouts/{start}/{end}",headers=_headers(access))
    need(r.status_code==200,"NATIVE_LIST_HTTP_"+str(r.status_code))
    d=r.json()
    d=d.get("data") if isinstance(d,dict) else d
    need(isinstance(d,list),"NATIVE_LIST_SHAPE")
    return d

def native_key(x):
    return ((x.get("title") or "").strip(),str(x.get("prescribedDate") or "")[:10])

async def main():
    async with TPClient() as c:
        me=await c._get_user_data()
        need(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        ph=await c.get(f"/plans/v1/plans/{P}")
        need(not ph.is_error and isinstance(ph.data,dict),"PLAN_READ")
        p=ph.data
        need(p.get("planId")==P and p.get("isPublic") is True and p.get("weekCount")==24
             and p.get("workoutCount")==EXPECTED_META_COUNT and "Beginner" in (p.get("title") or ""),"PLAN_GUARD")
        start=str(p.get("startDate") or "")[:10]
        end=(date.fromisoformat(start)+timedelta(weeks=24,days=2)).isoformat()
        classic=await classic_all(c,start,end)
        source=[w for w in classic if wid(w) in SOURCE_IDS]
        need(len(source)==36 and {wid(w) for w in source}==SOURCE_IDS,"SOURCE_SET_DRIFT")
        need(all(w.get("workoutTypeValueId")==9 and w.get("structure") is None for w in source),"SOURCE_NOT_TEXT_STRENGTH")
        # Precompile every source before first write.
        manifest=[]
        for w in sorted(source,key=lambda x:(str(x.get("workoutDay") or "")[:10],wid(x))):
            blocks=blocks_for(w)
            manifest.append({
              "source_id":wid(w),"date":str(w.get("workoutDay") or "")[:10],
              "source_title":w.get("title"),"title":clean_title(w.get("title")),
              "duration_min":round(float(w.get("totalTimePlanned") or 0)*60),
              "blocks":blocks,"instructions":instructions_for(w)
            })
        need(len(manifest)==36,"MANIFEST_COUNT")
        if not BACKUP.exists():
            BACKUP.parent.mkdir(parents=True,exist_ok=True)
            BACKUP.write_text(json.dumps({"plan":P,"plan_meta":p,"sources":{str(wid(w)):w for w in source},"manifest":manifest},ensure_ascii=False,default=str,indent=2)+"\n")
        _,access,err=await _access(c)
        need(err is None and access,"STRENGTH_AUTH")
        try:
            calendar_id=int(p.get("planPersonId"))
        except Exception:
            calendar_id=0
        need(calendar_id>0,"PLAN_PERSON_ID")
        async with httpx.AsyncClient(timeout=30.0) as h:
            existing=await native_all(h,access,start,end)
            # On initial migration no Beginner native Strength should exist.
            expected_keys={(z["title"],z["date"]) for z in manifest}
            unrelated=[x for x in existing if native_key(x) not in expected_keys]
            need(not unrelated,"UNRELATED_NATIVE_STRENGTH_PRESENT")
            print(json.dumps({"stage":"BEGINNER_STRENGTH_PREFLIGHT_PASS","classic_strength":36,
              "native_existing":len(existing),"variants_compiled":36}),flush=True)

            created=[]
            # Golden-first is manifest[0]. Subsequent items use same verified route.
            for idx,z in enumerate(manifest):
                current=await native_all(h,access,start,end)
                matches=[x for x in current if native_key(x)==(z["title"],z["date"])]
                if len(matches)==1:
                    created.append(str(matches[0].get("id")))
                    continue
                need(len(matches)==0,"DUPLICATE_NATIVE_SLOT_"+str(z["source_id"]))
                payload=_build_payload(calendar_id,z["date"],z["title"],z["blocks"],z["instructions"])
                try:
                    resp=await h.post(f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{P}/workouts/save",
                                      headers=_headers(access),json=payload)
                except httpx.RequestError:
                    # reconcile actual provider state before deciding
                    now=await native_all(h,access,start,end)
                    mm=[x for x in now if native_key(x)==(z["title"],z["date"])]
                    need(len(mm)==1,"AMBIGUOUS_NATIVE_POST_"+str(z["source_id"]))
                    created.append(str(mm[0].get("id"))); continue
                need(resp.status_code==200,"NATIVE_POST_REJECTED_"+str(z["source_id"])+"_"+str(resp.status_code))
                body=resp.json().get("data") or {}
                nid=str(body.get("id") or payload["id"])
                detail=await h.get(f"{STRENGTH_API_BASE}/rx/activity/v1/workouts/{nid}",headers=_headers(access))
                need(detail.status_code==200,"NATIVE_DETAIL_READ_"+str(z["source_id"]))
                nd=detail.json().get("data") or {}
                need(nd.get("workoutType")=="StructuredStrength" and nd.get("title")==z["title"]
                     and str(nd.get("prescribedDate") or "")[:10]==z["date"],"NATIVE_DETAIL_DRIFT_"+str(z["source_id"]))
                need((nd.get("snapshot") or {}).get("totalSets")==sum(len(e["sets"]) for b in z["blocks"] for e in b["exercises"]),
                     "NATIVE_SET_COUNT_"+str(z["source_id"]))
                need(all((pr.get("exercise") or {}).get("videoUrl") for b in nd.get("blocks") or [] for pr in b.get("prescriptions") or []),
                     "NATIVE_VIDEO_MISSING_"+str(z["source_id"]))
                created.append(nid)
                if idx==0:
                    print(json.dumps({"stage":"GOLDEN_NATIVE_STRENGTH_PASS","source_id":z["source_id"],
                      "native_id":nid,"title":z["title"]}),flush=True)
                else:
                    print(json.dumps({"stage":"NATIVE_STRENGTH_VERIFIED","n":idx+1,"source_id":z["source_id"],"native_id":nid}),flush=True)

            all_native=await native_all(h,access,start,end)
            need(len(all_native)==36 and {native_key(x) for x in all_native}==expected_keys,"NATIVE_36_NOT_EXACT")
            # Ensure plan count grew by 36 before removing any classic source.
            ph2=await c.get(f"/plans/v1/plans/{P}")
            need(not ph2.is_error and ph2.data.get("workoutCount")==EXPECTED_META_COUNT+36,"PLAN_COUNT_AFTER_NATIVE")
            print(json.dumps({"stage":"ALL_36_NATIVE_VERIFIED_BEFORE_DELETE","native_strength":36,
              "plan_count":ph2.data.get("workoutCount")}),flush=True)

            # Delete classic text Strength only after all native replacements exist.
            deleted=0
            originals={str(wid(w)):stable(w) for w in source}
            for z in manifest:
                current=await classic_all(c,start,end)
                by={wid(x):x for x in current}
                sid=z["source_id"]
                if sid not in by:
                    continue
                need(stable(by[sid])==originals[str(sid)],"CLASSIC_SOURCE_DRIFT_"+str(sid))
                # Confirm native twin at same relative slot immediately before destructive call.
                now=await native_all(h,access,start,end)
                need(len([x for x in now if native_key(x)==(z["title"],z["date"])])==1,"NATIVE_TWIN_MISSING_"+str(sid))
                res=await c._request("DELETE",f"/plans/v1/plans/{P}/workouts/{sid}",_retry_on_401=False)
                after=await classic_all(c,start,end)
                ids={wid(x) for x in after}
                need(sid not in ids,"CLASSIC_DELETE_UNVERIFIED_"+str(sid))
                # No blind repeat even if HTTP result is odd: provider readback is authority.
                deleted+=1
                print(json.dumps({"stage":"CLASSIC_STRENGTH_DELETE_VERIFIED","n":deleted,"source_id":sid}),flush=True)

            final_classic=await classic_all(c,start,end)
            final_native=await native_all(h,access,start,end)
            need(not any(wid(x) in SOURCE_IDS for x in final_classic),"CLASSIC_STRENGTH_REMAINS")
            need(len(final_classic)==189,"CLASSIC_FINAL_COUNT")
            need(len(final_native)==36 and {native_key(x) for x in final_native}==expected_keys,"FINAL_NATIVE_SET")
            pf=await c.get(f"/plans/v1/plans/{P}")
            need(not pf.is_error and pf.data.get("workoutCount")==225 and pf.data.get("isPublic") is True,"FINAL_PLAN_META")
            print(json.dumps({"stage":"BEGINNER_STRENGTH_NATIVE_MIGRATION_VERIFIED","plan":P,
              "native_strength":36,"classic_strength":0,"classic_nonstrength":189,
              "provider_workout_count":225,"public_state_preserved":True,
              "videos_verified":True}),flush=True)

if __name__=="__main__":
    try: asyncio.run(main())
    except Exception as e:
        print(json.dumps({"stage":"SAFE_STOP","reason":str(e)[:700]}),flush=True)
        raise
