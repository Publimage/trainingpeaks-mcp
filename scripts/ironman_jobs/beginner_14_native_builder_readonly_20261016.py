"""Read-only native Builder audit: 14 specified Beginner plan instances.
Uses native plan-workout GET. Absolutely no provider writes.
"""
import asyncio, json
from datetime import date, timedelta
from tp_mcp.client import TPClient
P=679801
OWNER=2116886
EXPECTED=[
(13,3978611963,3,120),(13,3978611934,2,64),
(14,3978612079,3,125),(14,3978611998,2,86),
(15,3978611986,3,130),(15,3978612017,2,85),
(17,3978612028,3,130),(17,3978612020,2,95),
(18,3978612029,3,135),(18,3978611970,2,94),
(19,3978612039,3,140),(19,3978611958,2,70),
(21,3978612034,3,120),(21,3978612108,2,80)]
def need(x,msg):
    if not x:raise RuntimeError(msg)
def audit(w):
    st=w.get("structure") or {}
    groups=st.get("structure") or []
    steps=[]
    seconds=0
    problems=[]
    for gi,g in enumerate(groups):
        count=int((g.get("length") or {}).get("value",1)) if g.get("type")=="repetition" else 1
        for si,step in enumerate(g.get("steps") or []):
            length=step.get("length") or {}
            value=length.get("value")
            unit=length.get("unit")
            if unit!="second" or not isinstance(value,(int,float)):problems.append("INVALID_STEP_LENGTH")
            else:seconds+=count*value
            targets=step.get("targets") or []
            if step.get("intensityClass")=="active" and not targets:problems.append("EMPTY_ACTIVE_TARGET")
            steps.append({"group":gi,"step":si,"repeats":count,
                          "class":step.get("intensityClass"),"name":step.get("name"),
                          "length":length,"targets":targets})
    top=w.get("totalTimePlanned")
    top_secs=round(top*3600) if isinstance(top,(int,float)) else None
    if not groups or not steps:problems.append("NO_NATIVE_STEPS")
    if not st.get("polyline"):problems.append("NO_POLYLINE")
    if top_secs is None or abs(seconds-top_secs)>2:problems.append("BUILDER_TIME_MISMATCH")
    return {"workout_id":w.get("workoutId"),"title":w.get("title"),
            "planned_minutes":round(top*60,3) if isinstance(top,(int,float)) else None,
            "native_seconds":seconds,"top_seconds":top_secs,
            "primaryIntensityMetric":st.get("primaryIntensityMetric"),
            "primaryLengthMetric":st.get("primaryLengthMetric"),
            "polyline_points":len(st.get("polyline") or []),
            "steps":steps,"problems":sorted(set(problems))}
async def main():
    async with TPClient() as client:
        me=await client._get_user_data()
        need(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        rp=await client.get(f"/plans/v1/plans/{P}")
        need(not rp.is_error and isinstance(rp.data,dict),"PLAN_READ_FAILED")
        p=rp.data
        need(p.get("planId")==P and p.get("isPublic") is True and
             p.get("workoutCount")==254 and "Beginner" in str(p.get("title")),"PLAN_GUARD_FAILED")
        dt=str(p.get("startDate") or "")[:10]
        try:anchor=date.fromisoformat(dt)
        except ValueError:raise RuntimeError("NO_PLAN_ANCHOR")
        observed={}
        for part in range(3):
            start=anchor+timedelta(weeks=8*part)
            end=anchor+timedelta(weeks=8*(part+1),days=-1)
            z=await client.get(f"/plans/v1/plans/{P}/workouts/{start.isoformat()}/{end.isoformat()}")
            need(not z.is_error and isinstance(z.data,list),"NATIVE_READ_FAILED_"+str(part))
            for w in z.data:
                ident=w.get("workoutId")
                need(ident not in observed,"DUPLICATE_INSTANCE_ID")
                observed[ident]=w
        report=[]
        for wk,wid,sport,minute in EXPECTED:
            w=observed.get(wid)
            need(w is not None,"MISSING_TARGET_"+str(wid))
            need(w.get("workoutTypeValueId")==sport,"SPORT_DRIFT_"+str(wid))
            need(abs((w.get("totalTimePlanned") or 0)*60-minute)<.02,"DURATION_DRIFT_"+str(wid))
            day=date.fromisoformat(str(w.get("workoutDay"))[:10])
            need((day-anchor).days//7+1==wk,"RELATIVE_WEEK_DRIFT_"+str(wid))
            result=audit(w)
            result["week"]=wk
            result["sport"]="RUN" if sport==3 else "BIKE"
            report.append(result)
        flag=[{"week":w["week"],"id":w["workout_id"],"issues":w["problems"]} for w in report if w["problems"]]
        print(json.dumps({"stage":"READ_ONLY_NATIVE_BUILDER_AUDIT","plan":P,
            "target_count":len(report),"full_plan_workouts_seen":len(observed),
            "native_pass":len(report)-len(flag),"native_issues":flag,
            "workouts":report,"provider_writes":0},ensure_ascii=False,default=str),flush=True)
        return 0 if not flag else 2
if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
