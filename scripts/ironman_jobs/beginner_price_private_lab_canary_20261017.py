"""Lab-only probe for plan-level price PUT semantics. NO live plan modifications.
One controlled temporary price change on disposable private plan 684484 and exact rollback.
Only proves whether this PRIVATE endpoint behaves safely; public price requires separate job.
"""
from __future__ import annotations
import asyncio
import json
from tp_mcp.client import TPClient

OWNER=2116886
LAB=684484
LAB_TITLE="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
EXPECTED_NOTES={2655235,2651317}
ENDPOINT=f"/plans/v1/plans/{LAB}"

class Stop(Exception): pass
def must(ok, why):
    if not ok: raise Stop(why)

async def run():
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        async def read():
            p=await c.get(ENDPOINT)
            must(not p.is_error and isinstance(p.data,dict),"LAB_GET_FAILED")
            return p.data
        async def notes():
            n=await c.get(f"/plans/v1/plans/{LAB}/calendarNote/2027-07-05/2027-07-20")
            must(not n.is_error and isinstance(n.data,list),"LAB_NOTES_FAILED")
            return n.data
        old=await read()
        must(old.get("planId")==LAB and old.get("title")==LAB_TITLE,"LAB_IDENTITY_CHANGED")
        must(old.get("isPublic") is False and old.get("price") in (None,0)
             and old.get("weekCount")==1 and old.get("workoutCount")==0,
             "LAB_PRIVATE_BASELINE_CHANGED")
        n0=await notes()
        must({x.get("id") for x in n0}==EXPECTED_NOTES,"LAB_NOTES_CHANGED")
        n0sig=json.dumps(n0,sort_keys=True)
        print("LAB_PREFLIGHT_PASS",json.dumps({"plan":LAB,"public":False,
                "notes":len(n0),"price":old.get("price")}),flush=True)
        call=await c._request("PUT",ENDPOINT,json={"planId":LAB,"price":1.0},
                             _retry_on_401=False)
        after=await read()
        seen=after.get("price")
        # Do not blindly repeat PUT: even an error can have modified the provider.
        if seen not in (None,0):
            restore=await c._request("PUT",ENDPOINT,
                         json={"planId":LAB,"price":old.get("price")},
                         _retry_on_401=False)
            if restore.is_error:
                print("STOP_REVIEW_LAB_RESTORE_AMBIGUOUS",flush=True)
                return 3
        final=await read()
        n1=await notes()
        must(final.get("price")==old.get("price"),"LAB_PRICE_NOT_RESTORED")
        must(final.get("isPublic") is False,"LAB_BECAME_PUBLIC")
        must(json.dumps(n1,sort_keys=True)==n0sig,"LAB_NOTES_CHANGED_BY_PUT")
        ignored={k for k in set(old)|set(final)
                 if ("modif" in k.lower() or "updat" in k.lower())}
        unexpected=[k for k in set(old)|set(final)
                    if k not in ignored and old.get(k)!=final.get(k)]
        must(not unexpected,"LAB_FINAL_METADATA_DRIFT:"+",".join(sorted(unexpected)))
        must(not call.is_error and seen==1.0,
             "LAB_PRICE_PUT_UNSUPPORTED_OR_NO_READBACK;PUBLIC_UNTOUCHED")
        must(after.get("isPublic") is False,"LAB_INTERMEDIATE_PUBLICATION_DRIFT")
        intermediate_drift=[k for k in set(old)|set(after)
                            if k not in ignored and k!="price" and old.get(k)!=after.get(k)]
        must(not intermediate_drift,
             "LAB_PUT_OTHER_FIELDS_CHANGED:"+",".join(sorted(intermediate_drift)))
        print("PRICE_CANARY_PASS",json.dumps({"plan":LAB,"temporary_price":1.0,
              "restored":True,"public":False,"public_plan_untouched":True}),flush=True)
        return 0

if __name__=="__main__":
    try: raise SystemExit(asyncio.run(run()))
    except Stop as e:
        print("STOP_REVIEW",str(e),flush=True)
        raise SystemExit(2)
