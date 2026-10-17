"""One-shot TrainingPeaks plan description UPDATE canary and rollback.
Provider writes restricted to disposable lab plan 684484. No athlete calendars.
"""
import asyncio, json
from tp_mcp.client import TPClient

OWNER=2116886
PLAN=684484
EXPECTED_TITLE="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
CANARY="<div><strong>IRONMAN PLAN DESCRIPTION CANARY</strong><p>Temporary verification only.</p></div>"

class Stop(Exception): pass
def must(v,msg):
    if not v: raise Stop(msg)

async def go():
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        async def detail():
            r=await c.get(f"/plans/v1/plans/{PLAN}")
            must(not r.is_error and isinstance(r.data,dict),"PLAN_READ_FAILED")
            return r.data
        p=await detail()
        must(p.get("planId")==PLAN and p.get("title")==EXPECTED_TITLE and p.get("workoutCount")==0
             and p.get("weekCount")==1 and p.get("isPublic") is False,"LAB_SCOPE_CHANGED")
        old=p.get("description")
        baseline={k:v for k,v in p.items() if k!="description"}
        put=await c._request("PUT",f"/plans/v1/plans/{PLAN}",
            json={"planId":PLAN,"title":EXPECTED_TITLE,"description":CANARY},_retry_on_401=False)
        if put.is_error:
            print("CANARY_PUT_REJECTED",put.error_code,str(put.message)[:120],flush=True)
            return 3
        p2=await detail()
        must(p2.get("description")==CANARY,"DESCRIPTION_READBACK_FAILED")
        must({k:v for k,v in p2.items() if k!="description"}==baseline,"CANARY_DRIFT")
        print("PLAN_DESCRIPTION_CANARY_CHANGED_VERIFIED",flush=True)
        rb=await c._request("PUT",f"/plans/v1/plans/{PLAN}",
            json={"planId":PLAN,"title":EXPECTED_TITLE,"description":old},_retry_on_401=False)
        must(not rb.is_error,"CANARY_ROLLBACK_ERROR")
        p3=await detail()
        must(p3==p,"CANARY_ROLLBACK_MISMATCH")
        print("PLAN_DESCRIPTION_CANARY_RESTORED_VERIFIED",flush=True)
        return 0

if __name__=="__main__":
    try: raise SystemExit(asyncio.run(go()))
    except Stop as e:
        print("STOP_REVIEW",str(e),flush=True)
        raise SystemExit(2)
