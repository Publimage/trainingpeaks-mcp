"""CHASING 685173 W01: exactly three native Builder target-only conversions.
No changes to plan content, workouts, titles, notes, library or athlete calendars.
Plan dates are only API transport. Identity uses (week, weekday, workout ID).
"""
import asyncio
import copy
import hashlib
import json
from datetime import date
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.library import _ensure_structure_preview

PLAN=685173
OWNER=2116886
PERSON=6682479
START=date(2027,1,4)
RANGE=("2027-01-04","2027-02-28")
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w01_three_builder_delta_backup_20261014.json"
# (id, sport code, weekday zero-indexed, planned minutes, metric, warm, active, cool)
CANARIES=(
    (4000490146,3,3,35,"percentOfThresholdPace",((76,82),(78,84),(70,78))),
    (4000490183,2,5,190,"percentOfFtp",((50,60),(60,70),(45,55))),
    (4000490091,3,6,65,"percentOfThresholdPace",((76,82),(80,86),(70,78))),
)
STEP_SECONDS={4000490146:(480,1260,360),4000490183:(1200,9600,600),4000490091:(720,2700,480)}
STEP_CLASSES=("warmUp","active","coolDown")

def need(test,code):
    if not test: raise RuntimeError(code)
def canon(w):
    return {k:v for k,v in w.items() if k!="lastModifiedDate"}
def digest(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def loc(w):
    days=(date.fromisoformat(str(w["workoutDay"])[:10])-START).days
    return days//7+1,days%7

async def read(c):
    r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{RANGE[0]}/{RANGE[1]}")
    n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{RANGE[0]}/{RANGE[1]}")
    need(not r.is_error and not n.is_error and len(r.data)==79,"W01_W08_READ_OR_COUNT_DRIFT")
    need(len({x["workoutId"] for x in r.data})==79,"DUPLICATE_IDS")
    return r.data,digest(n.data)

def steps(s):
    return [v for g in s.get("structure") or [] for v in g.get("steps") or []]

def make_patch(w,spec):
    wid,sport,wd,minutes,metric,ranges=spec
    need(w["workoutId"]==wid and w["workoutTypeValueId"]==sport,"WRONG_WORKOUT")
    need(loc(w)==(1,wd),"WRONG_WEEK_DAY")
    need(abs(w["totalTimePlanned"]*60-minutes)<0.03,"DURATION_DRIFT")
    original=w["structure"]
    need(isinstance(original,dict) and original.get("primaryLengthMetric")=="duration","MISSING_DURATION_BUILDER")
    need(original.get("primaryIntensityMetric")=="rpe","NOT_ORIGINAL_RPE")
    st=steps(original)
    need(len(st)==3,"WRONG_BLOCK_COUNT")
    for i,v in enumerate(st):
        need(v.get("intensityClass")==STEP_CLASSES[i],"WRONG_INTENSITY_CLASS")
        need(v.get("length",{}).get("value")==STEP_SECONDS[wid][i],"WRONG_SEGMENT_DURATION")
        need(len(v.get("targets") or [])==1,"SOURCE_STEP_TARGET_MISSING")
    q=copy.deepcopy(w)
    s=q["structure"]
    for v,(lo,hi) in zip(steps(s),ranges):
        v["targets"][0]["minValue"]=lo
        v["targets"][0]["maxValue"]=hi
    s["primaryIntensityMetric"]=metric
    s["primaryIntensityTargetOrRange"]="range"
    s.pop("polyline",None)
    q["structure"]=_ensure_structure_preview(s)
    need(len(q["structure"].get("polyline") or [])>=4,"POLYLINE_NOT_REGENERATED")
    need({k:v for k,v in q.items() if k!="structure"}=={k:v for k,v in w.items() if k!="structure"},"TOP_LEVEL_NON_BUILDER_DRIFT")
    aa=copy.deepcopy(original);bb=copy.deepcopy(q["structure"])
    for x in (aa,bb):
        for k in ("primaryIntensityMetric","primaryIntensityTargetOrRange","polyline"):
            x.pop(k,None)
        for v in steps(x):
            v.pop("targets",None)
    need(aa==bb,"UNEXPECTED_BUILDER_STRUCTURE_DRIFT")
    need("RPE" in (q.get("description") or ""),"TEXT_RPE_MISSING")
    return q

async def main():
    async with TPClient() as c:
        who=await c._get_user_data()
        need(who.get("personId")==OWNER,"WRONG_ACCOUNT")
        pr=await c.get(f"/plans/v1/plans/{PLAN}")
        h=pr.data
        need(not pr.is_error and h.get("planId")==PLAN and h.get("planPersonId")==PERSON
             and h.get("isPublic") is False and h.get("workoutCount")==276
             and "BOZZA" in (h.get("title") or ""),"WRONG_PLAN_OR_PUBLIC")
        before,nhash=await read(c)
        by={w["workoutId"]:w for w in before}
        patches={}
        for spec in CANARIES:
            wid=spec[0]
            need(wid in by,"CANARY_ID_MISSING")
            patches[wid]=make_patch(by[wid],spec)
        need(not BACKUP.exists(),"BACKUP_EXISTS_VERIFY_BEFORE_RETRY")
        BACKUP.parent.mkdir(parents=True,exist_ok=True)
        BACKUP.write_text(json.dumps({"plan":PLAN,"original":before,"notehash":nhash,
          "targets":list(patches)},ensure_ascii=False,indent=2)+"\n")
        expected={w["workoutId"]:canon(w) for w in before}
        print(json.dumps({"stage":"PREFLIGHT_PASS","plan":PLAN,"private":True,
          "target_ids":list(patches),"unaffected_in_range":76}),flush=True)
        for wid,q in patches.items():
            current,cur_notes=await read(c)
            cm={w["workoutId"]:w for w in current}
            need(cur_notes==nhash and canon(cm[wid])==expected[wid],"PREWRITE_DRIFT_"+str(wid))
            res=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",
                                  json=q,_retry_on_401=False)
            now,nn=await read(c)
            nm={w["workoutId"]:w for w in now}
            need(not res.is_error and nn==nhash and canon(nm[wid])==canon(q),
                 "WRITE_NOT_VERIFIED_"+str(wid))
            expected[wid]=canon(q)
            need(all(canon(nm[k])==v for k,v in expected.items()),
                 "UNEXPECTED_OTHER_WORKOUT_CHANGE_"+str(wid))
            need(nm[wid]["structure"]["primaryIntensityMetric"]==q["structure"]["primaryIntensityMetric"],
                 "NATIVE_METRIC_MISMATCH_"+str(wid))
            print(json.dumps({"stage":"CANARY_VERIFIED","id":wid,
              "week":loc(nm[wid])[0],"weekday":loc(nm[wid])[1],
              "metric":nm[wid]["structure"]["primaryIntensityMetric"]}),flush=True)
        last,ln=await read(c)
        need(ln==nhash and all(canon(w)==expected[w["workoutId"]] for w in last),
             "FINAL_UNEXPECTED_DELTA")
        print(json.dumps({"stage":"PASS_THREE_BUILDER_ONLY","written":3,
          "unaffected":76,"no_athlete_writes":True,"plan_private":True}),flush=True)

if __name__=="__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({"stage":"STOP_CHECK_PROVIDER","error":str(exc)[:300]}),flush=True)
        raise
