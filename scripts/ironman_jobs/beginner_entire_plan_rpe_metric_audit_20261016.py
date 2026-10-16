"""READ_ONLY: inventory Beginner native training-plan intensity metrics, 24 weeks.
No calendar changes, no power-meter requirement assumptions.
"""
import asyncio, json
from datetime import date,timedelta
from collections import Counter
from tp_mcp.client import TPClient
PLAN=679801
OWNER=2116886
def check(ok,why):
    if not ok:raise RuntimeError(why)
async def main():
    async with TPClient() as c:
        me=await c._get_user_data()
        check(me.get("personId")==OWNER,"COACH_ACCOUNT_DRIFT")
        rp=await c.get(f"/plans/v1/plans/{PLAN}")
        check(not rp.is_error and isinstance(rp.data,dict),"PLAN_METADATA_ERROR")
        plan=rp.data
        check(plan.get("planId")==PLAN and plan.get("planPersonId")==OWNER and plan.get("workoutCount")==254 and plan.get("isPublic") is True and "Beginner" in plan.get("title",""),"PLAN_IDENTITY_DRIFT")
        anchor=date.fromisoformat(str(plan["startDate"])[:10])
        allw={}
        for n in range(3):
            start=anchor+timedelta(weeks=n*8)
            end=start+timedelta(days=55)
            result=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{start.isoformat()}/{end.isoformat()}")
            check(not result.is_error and isinstance(result.data,list),"PROVIDER_READ_FAILED")
            for w in result.data:
                wid=w.get("workoutId")
                check(wid not in allw,"DUPLICATE_ID")
                allw[wid]=w
        check(len(allw)==254,"PLAN_WORKOUT_COUNT_DRIFT")
        counts=Counter()
        mismatch=[]
        non_rpe=[]
        for w in allw.values():
            typ=w.get("workoutTypeValueId")
            if typ not in (1,2,3):continue
            key={1:"SWIM",2:"BIKE",3:"RUN"}[typ]
            st=w.get("structure") or {}
            metric=st.get("primaryIntensityMetric")
            counts[(key,str(metric))]+=1
            if typ not in (2,3):continue
            wk=1+(date.fromisoformat(str(w["workoutDay"])[:10])-anchor).days//7
            if metric!="rpe":
                ss=[]
                for g in st.get("structure") or []:
                    for step in g.get("steps") or []:
                        ss.append({"name":step.get("name"),"class":step.get("intensityClass"),
                            "unit":(step.get("length") or {}).get("unit"),
                            "seconds":(step.get("length") or {}).get("value"),
                            "targets":step.get("targets"),
                            "repeats":(g.get("length") or {}).get("value") if g.get("type")=="repetition" else 1})
                non_rpe.append({"id":w["workoutId"],"week":wk,"sport":key,
                    "title":w.get("title"),"metric":metric,
                    "totalTimePlanned":w.get("totalTimePlanned"),"steps":ss})
            if not st.get("structure") or not st.get("polyline"):
                mismatch.append({"id":w["workoutId"],"sport":key,"why":"MISSING_STEPS_OR_POLYLINE"})
        print(json.dumps({"type":"BEGINNER_RPE_AUDIT","plan":PLAN,"all_workouts":len(allw),
           "metric_counts":[{"sport":k[0],"metric":k[1],"count":v} for k,v in sorted(counts.items())],
           "bike_run_non_rpe_count":len(non_rpe),"non_rpe":non_rpe,
           "bike_run_missing_builder":mismatch,
           "provider_writes":0},ensure_ascii=False,default=str),flush=True)
        return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
