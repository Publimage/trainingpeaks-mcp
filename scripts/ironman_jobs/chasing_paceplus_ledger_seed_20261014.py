"""Backfill one approved, COMPLETED nine-workout operation into durable DO SQLite.

Only GETs TrainingPeaks for nine known plan-scoped BI workouts and commits state
after their live structural evidence passes. ZERO provider writes.
"""
import asyncio
import json
from datetime import date,timedelta
from tp_mcp.client import TPClient
from chasing_paceplus_nine_20261014 import P,OWNER,PERSON,SETS,need
from ironman_state_store_v1 import connect,digest,record_verified_snapshot,read_snapshot,DB_PATH

JOB_ID="chasing-685173-paceplus-20261014-v1"
SOURCE="drive:02_DECISION_LOG:2026-10-14:PACEPLUS-76-80; github:441642338e5154340ae2c87233363accde37cc52"
PROVIDER="TrainingPeaks-Plan-Private"
START=date(2027,1,4)

def verify(w,wid):
    wk,weekday,reps,orig,normal,plus,rest,lead,finish,easy=SETS[wid]
    dt=START+timedelta(days=(wk-1)*7+weekday)
    need(w.get("workoutId")==wid and w.get("workoutTypeValueId")==2,"WRONG_ID_OR_SPORT")
    need(str(w.get("workoutDay",""))[:10]==dt.isoformat(),"WRONG_RELATIVE_SLOT")
    need(abs((w.get("totalTimePlanned") or 0)*60-
         (lead+reps*(orig+rest)+finish+easy))<0.01,"DURATION_DRIFT")
    description=w.get("description") or ""
    need("Ironman Pace" in description and "Ironman Pace+" in description,"LABELS_DRIFT")
    structure=w.get("structure") or {}
    need(structure.get("primaryLengthMetric")=="duration"
         and structure.get("primaryIntensityMetric")=="percentOfFtp","METRIC_DRIFT")
    groups=[x for x in structure.get("structure") or [] if x.get("type")=="repetition"]
    need(len(groups)==1 and groups[0].get("length",{}).get("value")==reps,"REPS_DRIFT")
    steps=groups[0].get("steps") or []
    need(len(steps)==3,"THREE_SPLIT_STEPS_EXPECTED")
    active={s.get("name"):s for s in steps if s.get("intensityClass")=="active"}
    need(set(active)=={"Ironman Pace","Ironman Pace+"},"PACE_STEP_NAMES_DRIFT")
    for title,mins,target in [
        ("Ironman Pace",normal,[{"minValue":71,"maxValue":75}]),
        ("Ironman Pace+",plus,[{"minValue":76,"maxValue":80}])]:
        s=active[title]
        need(s.get("length")=={"value":mins*60,"unit":"second"} and s.get("targets")==target,
             "PACE_TARGET_DRIFT_"+str(wid))
    need(any(s.get("intensityClass")=="rest" and
            s.get("length")=={"value":rest*60,"unit":"second"} for s in steps),"REST_DRIFT")
    return {
        "item_id":wid,"relative_week":wk,
        "duration_min":lead+reps*(orig+rest)+finish+easy,
        "provider_evidence_sha256":digest({
           "workoutId":wid,"workoutDay":str(w.get("workoutDay"))[:10],
           "description":description,"totalTimePlanned":w.get("totalTimePlanned"),
           "structure":structure
        })
    }

async def main():
    async with TPClient() as c:
        me=await c._get_user_data()
        need(me.get("personId")==OWNER,"OWNER_MISMATCH")
        p=await c.get(f"/plans/v1/plans/{P}")
        h=p.data or {}
        need(not p.is_error and h.get("planId")==P
             and h.get("planPersonId")==PERSON
             and h.get("isPublic") is False
             and h.get("workoutCount")==276
             and "BOZZA" in (h.get("title") or ""),"PLAN_SCOPE_DRIFT")
        observed={}
        for wk in sorted(set(z[0] for z in SETS.values())):
            a=START+timedelta(weeks=wk-1)
            b=a+timedelta(days=6)
            response=await c.get(
               f"/plans/v1/plans/{P}/workouts/{a.isoformat()}/{b.isoformat()}")
            need(not response.is_error and isinstance(response.data,list),"WEEK_READ_FAIL")
            for w in response.data:
                if w.get("workoutId") in SETS:
                    need(w["workoutId"] not in observed,"DUPLICATE_PROVIDER_ID")
                    observed[w["workoutId"]]=w
        need(set(observed)==set(SETS),"MISSING_PROVIDER_TARGET")
        rows=[verify(observed[wid],wid) for wid in sorted(SETS)]
    # No persistent mutation until all nine independent provider checks pass.
    db=connect()
    try:
        outcome=record_verified_snapshot(db,JOB_ID,SOURCE,PROVIDER,P,rows)
        readback=read_snapshot(db,JOB_ID)
    finally:db.close()
    need(readback["expected_items"]==9
         and readback["state"]=="DONE_VERIFIED","DB_VERIFICATION_FAIL")
    print(json.dumps({"stage":"DO_LEDGER_SNAPSHOT_VERIFIED",
      "job_id":JOB_ID,"state":readback["state"],
      "items":readback["expected_items"],"weeks":sorted({r["relative_week"] for r in rows}),
      "db_path":str(DB_PATH),"db_written_new":outcome["created"],
      "evidence_digest":readback["evidence_digest"],
      "provider_writes":0},sort_keys=True),flush=True)

if __name__=="__main__":
    asyncio.run(main())
