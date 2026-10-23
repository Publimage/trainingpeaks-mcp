"""Read-only post-repair QA for CHASING: all 249 native Builders and exact 35-instance backup delta."""
import asyncio, json, hashlib, collections
from pathlib import Path
from datetime import date
from tp_mcp.client import TPClient
from chasing_native_builder_repair_35 import TEMPLATES, BACKUP, RANGES, P, OWNER, PERSON, TITLE

def must(ok, msg):
    if not ok: raise RuntimeError(msg)
def dig(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def stable(w):
    return {k:v for k,v in w.items() if k != "lastModifiedDate"}
def day(w):
    return str(w.get("workoutDay") or "")[:10]
def week(w):
    return (date.fromisoformat(day(w))-date(2027,1,4)).days//7+1
def problem(s):
    if not isinstance(s,dict) or not isinstance(s.get("structure"),list) or not s["structure"]:
        return "MISSING_STRUCTURE"
    if any(z.get("intensityClass")=="active" and not z.get("targets") for g in s["structure"] for z in g.get("steps") or []):
        return "ACTIVE_TARGET_EMPTY"
    pts=s.get("polyline")
    if not isinstance(pts,list) or len(pts)<4 or not all(isinstance(p,list) and len(p)==2 and all(isinstance(v,(int,float)) for v in p) for p in pts):
        return "MISSING_OR_BAD_POLYLINE"
    if not (abs(pts[0][0]) < .0001 and abs(pts[-1][0]-1) < .0002):
        return "POLYLINE_ENDPOINTS"
    if any(pts[i][0]>pts[i+1][0]+.0001 for i in range(len(pts)-1)):
        return "POLYLINE_X_OUT_OF_ORDER"
    if max(p[1] for p in pts)<=0: return "POLYLINE_ALL_ZERO"
    return None
def geometry(s):
    if not isinstance(s,dict): return None
    out=[]
    for g in s.get("structure") or []:
        out.append({"type":g.get("type"),"length":g.get("length"),"begin":g.get("begin"),"end":g.get("end"),
           "steps":[{"name":z.get("name"),"length":z.get("length"),"intensityClass":z.get("intensityClass"),
                     "openDuration":z.get("openDuration")} for z in g.get("steps") or []]})
    return out
async def main():
    async with TPClient() as c:
        me=await c._get_user_data()
        must(me.get("personId")==OWNER, "OWNER_MISMATCH")
        p=await c.get(f"/plans/v1/plans/{P}")
        h=p.data
        must(not p.is_error and h.get("planId")==P and h.get("planPersonId")==PERSON and h.get("title")==TITLE and h.get("isPublic") is False and h.get("workoutCount")==276, "PLAN_SCOPE_DRIFT")
        rows=[]; notes=[]
        for st,en in RANGES:
            a=await c.get(f"/plans/v1/plans/{P}/workouts/{st}/{en}")
            n=await c.get(f"/plans/v1/plans/{P}/calendarNote/{st}/{en}")
            must(not a.is_error and not n.is_error and isinstance(a.data,list) and isinstance(n.data,list), "READ_FAIL")
            rows.extend(a.data);notes.append(n.data)
        must(len(rows)==249 and len({x["workoutId"] for x in rows})==249,"249_IDS_COUNT_DRIFT")
        now={w["workoutId"]:w for w in rows}
        expected={wid:(lid,tid) for lid,tid,ids in TEMPLATES for wid in ids}
        must(len(expected)==35,"MANIFEST_35_DRIFT")
        libs={}
        for lid in {lid for lid,_,_ in TEMPLATES}:
            l=await c.get(f"/exerciselibrary/v2/libraries/{lid}/items")
            must(not l.is_error and isinstance(l.data,list),"LIBRARY_READ_FAILED")
            libs[lid]={x.get("exerciseLibraryItemId"):x for x in l.data}
        errors=[]; warnings=[]; manifest=[]
        for w in rows:
            wid=w["workoutId"]
            issue=problem(w.get("structure"))
            if issue: errors.append([wid,issue])
            dur=(w.get("totalTimePlanned") or 0)*3600
            if dur<=0:errors.append([wid,"DURATION_NONPOSITIVE"])
            s=w.get("structure")
            if isinstance(s,dict):
                seg=s.get("structure") or []
                last=seg[-1].get("end") if seg else None
                if s.get("primaryLengthMetric")=="duration" and isinstance(last,(float,int)) and abs(last-dur)>2:
                    errors.append([wid,"BUILDER_DURATION_MISMATCH",last,dur])
                if s.get("primaryIntensityMetric")=="rpe":
                    for g in seg:
                        for step in g.get("steps") or []:
                            for target in step.get("targets") or []:
                                lo=target.get("minValue"); hi=target.get("maxValue")
                                if not isinstance(lo,(int,float)) or not isinstance(hi,(int,float)) or lo<0 or hi>10 or lo>hi:
                                    errors.append([wid,"BAD_RPE_RANGE",target])
            if w.get("workoutTypeValueId")==1:
                if not (w.get("distancePlanned") and w.get("totalTimePlanned")): errors.append([wid,"SWIM_TOP_LEVEL_MISSING"])
                if not isinstance(s,dict) or s.get("primaryLengthMetric")!="distance":errors.append([wid,"SWIM_NOT_DISTANCE_BASED"])
                elif isinstance(last,(int,float)) and abs(last-w["distancePlanned"])>0.1:
                    warnings.append([wid,"SWIM_BUILDER_DISTANCE_MISMATCH",w["distancePlanned"],last])
            if wid in expected:
                lid,tid=expected[wid]; t=libs[lid].get(tid)
                if t is None: errors.append([wid,"MODEL_NOT_FOUND",tid]);continue
                if t["itemName"].count("|")!=1 or "CHASING" in t["itemName"] or any(f"W{i:02d}" in t["itemName"] for i in range(1,25)):
                    errors.append([wid,"MODEL_NAMING_FAILED"])
                eq=all(w.get(a)==t.get(b) for a,b in [("title","itemName"),("description","description"),("structure","structure"),("totalTimePlanned","totalTimePlanned"),("distancePlanned","distancePlanned"),("workoutSubTypeId","workoutSubTypeId")])
                if not eq:errors.append([wid,"MODEL_PROVIDER_NOT_EXACT",tid])
                active=[{"name":z.get("name"),"rpe":z.get("targets")} for g in (s or {}).get("structure") or [] for z in g.get("steps") or [] if z.get("intensityClass")=="active"]
                manifest.append({"id":wid,"week":week(w),"sport":w.get("workoutTypeValueId"),"model":tid,"title":w.get("title"),"active":active})
        must(BACKUP.exists(),"REPAIR_BACKUP_NOT_FOUND")
        base=json.loads(BACKUP.read_text())
        must(base.get("plan")==P and len(base.get("source") or [])==249 and len(base.get("affected_ids") or [])==35,"BAD_BACKUP")
        prev={w["workoutId"]:w for w in base["source"]}
        if set(prev)!=set(now):errors.append(["ALL","WORKOUT_ID_SET_CHANGED"])
        if base.get("notehash")!=dig(notes):errors.append(["ALL","CALENDAR_NOTES_CHANGED"])
        if set(base["affected_ids"])!=set(expected):errors.append(["ALL","AFFECTED_MANIFEST_DIFFERS_FROM_BACKUP"])
        preserve=["workoutId","workoutDay","workoutTypeValueId","totalTimePlanned","distancePlanned","calendarId"]
        geom_changes=[];desc_changes=0;modified_unaffected=[]
        allowed={"title","description","totalTimePlanned","distancePlanned","structure","workoutSubTypeId"}
        for wid,old in prev.items():
            new=now.get(wid)
            if not new:continue
            changed={k for k in set(old)|set(new) if k!="lastModifiedDate" and old.get(k)!=new.get(k)}
            if wid not in expected:
                if changed: modified_unaffected.append({"id":wid,"changed":sorted(changed)})
            else:
                if changed-allowed:errors.append([wid,"UNEXPECTED_FIELDS_CHANGED",sorted(changed-allowed)])
                for k in preserve:
                    if old.get(k)!=new.get(k):errors.append([wid,"INVARIANT_CHANGED",k])
                if old.get("description")!=new.get("description"):desc_changes+=1
                if old.get("structure") is not None and geometry(old.get("structure"))!=geometry(new.get("structure")):
                    geom_changes.append(wid)
        if modified_unaffected:errors.append(["ALL","NON_AFFECTED_WORKOUTS_CHANGED",modified_unaffected[:12]])
        if geom_changes:warnings.append(["ALL","SEGMENT_NAMES_OR_GEOMETRY_CHANGED",geom_changes])
        oldweek={i:round(sum((v.get("totalTimePlanned") or 0)*60 for v in prev.values() if week(v)==i)) for i in range(1,25)}
        newweek={i:round(sum((v.get("totalTimePlanned") or 0)*60 for v in rows if week(v)==i)) for i in range(1,25)}
        if oldweek!=newweek:errors.append(["ALL","WEEKLY_VOLUMES_CHANGED"])
        stat=collections.Counter(v.get("workoutTypeValueId") for v in rows)
        print(json.dumps({"stage":"POST_REPAIR_QA_249","issues_count":len(errors),"errors":errors[:75],"warnings_count":len(warnings),
            "warnings":warnings[:85],"count":len(rows),"sport_counts":dict(stat),
            "models":len({tid for _,tid,_ in TEMPLATES}),"affected":len(expected),"unaffected":249-len(expected),
            "non_affected_drift":len(modified_unaffected),"target_polylines_gate":"passed" if not errors else "failed",
            "geometry_changed_count":len(geom_changes),"descriptions_changed":desc_changes,
            "backup_sha256":dig(base),"all_24_weekly_duration_preserved":oldweek==newweek,
            "notes_unchanged":base.get("notehash")==dig(notes),
            "manifest":sorted(manifest,key=lambda z:(z["week"],z["id"]))},
            ensure_ascii=False,default=str),flush=True)
        must(not errors,"POST_REPAIR_HARD_QA_FAILED")
        print(json.dumps({"stage":"POST_REPAIR_PROVIDER_VERIFIED","success":True,"count":249,"mapped_repaired":35,
                          "all_ids_and_weekly_durations_preserved":True,"notes_preserved":True},ensure_ascii=False),flush=True)
if __name__=="__main__":
    try: asyncio.run(main())
    except Exception as ex:
        print(json.dumps({"stage":"QA_STOP","reason":str(ex)[:450]},ensure_ascii=False),flush=True)
        raise
