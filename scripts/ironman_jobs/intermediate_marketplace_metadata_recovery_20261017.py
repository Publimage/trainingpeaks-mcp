"""Recover Intermediate plan metadata lost by provider partial PUT while preserving approved HTML."""
import asyncio, json
from tp_mcp.client import TPClient
OWNER=2116886
TARGET=684602
SOURCE=684463
LANG_SOURCE=679801
TITLE="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
EXPECTED_WORKOUTS=259
EXPECTED_WEEKS=24
class Stop(Exception): pass
def must(v,msg):
    if not v: raise Stop(msg)

async def go():
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        async def get(i):
            r=await c.get(f"/plans/v1/plans/{i}")
            must(not r.is_error and isinstance(r.data,dict),"PLAN_READ_FAIL")
            return r.data
        src=await get(SOURCE); lang=await get(LANG_SOURCE); p=await get(TARGET)
        must((p.get("planId"),p.get("title"),p.get("weekCount"),p.get("workoutCount"))==(TARGET,TITLE,EXPECTED_WEEKS,EXPECTED_WORKOUTS),"TARGET_SCOPE_MISMATCH")
        must(p.get("isPublic") is False and p.get("price") in (None,0),"TARGET_VISIBILITY_DRIFT")
        must(isinstance(p.get("description"),str) and "IRONMAN 24 settimane" in p["description"],"APPROVED_HTML_MISSING")
        for k in ("author","planEmail"):
            must(src.get(k) not in (None,""),"REFERENCE_METADATA_MISSING:"+k)
        must(lang.get("planLanguage") not in (None,""),"LANGUAGE_REFERENCE_MISSING")
        baseline={k:v for k,v in p.items() if k not in ("author","planEmail","planLanguage")}
        put=await c._request("PUT",f"/plans/v1/plans/{TARGET}",json={
            "planId":TARGET,
            "title":TITLE,
            "description":p["description"],
            "author":src["author"],
            "planEmail":src["planEmail"],
            "planLanguage":lang["planLanguage"],
        },_retry_on_401=False)
        if put.is_error:
            print("STOP_WRITE_RESULT_UNCLEAR",put.error_code,str(put.message)[:120],flush=True)
            return 2
        q=await get(TARGET)
        must(q.get("author")==src["author"] and q.get("planEmail")==src["planEmail"] and q.get("planLanguage")==lang["planLanguage"],"METADATA_NOT_RESTORED")
        for k,v in baseline.items():
            if k in ("modifiedDate","updatedDate","lastModifiedDate"): continue
            must(q.get(k)==v,"UNEXPECTED_DRIFT:"+k)
        print("INTERMEDIATE_METADATA_RECOVERY_VERIFIED")
        print(json.dumps({"plan_id":TARGET,"workouts":q.get("workoutCount"),"weeks":q.get("weekCount"),"is_public":q.get("isPublic"),"html_preserved":True},sort_keys=True))
        return 0
if __name__=="__main__":
    try: raise SystemExit(asyncio.run(go()))
    except Stop as e:
        print("STOP_REVIEW",str(e),flush=True); raise SystemExit(2)
