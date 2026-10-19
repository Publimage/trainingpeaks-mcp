"""Read-only native Builder snapshot for the approved private 70.3 Beginner plan.
No provider PUT/POST/DELETE and no athlete calendars. Used to prepare a manifest
for the existing reviewed plan patch publisher, never writes directly.
"""
import asyncio
import json
from tp_mcp.client import TPClient
from scripts.ironman_jobs.tp_plan_readonly_gateway import TrainingPeaksPlanReadGateway

PLAN=686994
TITLE="ALBERTO FAZI ENDURANCE | 70.3 | 16 settimane | Beginner | Italiano"
async def main():
    async with TPClient() as tp:
        g=TrainingPeaksPlanReadGateway(tp,PLAN,[("2027-01-04","2027-03-31"),("2027-04-01","2027-04-25")],expected_owner_id=2116886)
        assert await g.get_owner_id()==2116886,"OWNER"
        p=await g.get_plan(PLAN)
        assert p.get("title")==TITLE and p.get("isPublic") is False and p.get("workoutCount")==133 and p.get("weekCount")==16,"PLAN_DRIFT"
        allw=await g.list_workouts()
        assert len(allw)==118 and len({w["workoutId"] for w in allw})==118,"COUNT_DRIFT"
        sel=[]
        for w in allw:
            if w.get("workoutTypeValueId") not in (2,3):
                continue
            m=float(w.get("totalTimePlanned") or 0)*60
            if abs(m/5-round(m/5))<0.00001:
                continue
            assert m>0 and bool(w.get("structure")),"STRUCTURE_MISSING"
            sel.append({k:w.get(k) for k in ("workoutId","title","description","totalTimePlanned","workoutTypeValueId","workoutDay","structure")})
        assert len(sel)==26,"UNROUNDED_COUNT_DRIFT_{}".format(len(sel))
        print(json.dumps({"stage":"HALF_BEGINNER_NATIVE_BUILDER_READ_PASS","plan":PLAN,"all_count":len(allw),"count":len(sel),"rows":sel},ensure_ascii=False,separators=(",",":")),flush=True)
if __name__=="__main__":
    asyncio.run(main())
