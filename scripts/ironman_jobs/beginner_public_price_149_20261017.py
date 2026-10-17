"""One exact price-only update for the existing public Beginner plan 679801.

Never execute until private plan pricing canary succeeds, is audited, and the
scoped reviewed job is registered. Experimental internal plan API (not public
TrainingPeaks Partner API). This script cannot touch athlete calendars.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from tp_mcp.client import TPClient

OWNER=2116886
PLAN=679801
TITLE="ALBERTO FAZI ENDURANCE | First Ironman | 24 settimane | Beginner | Smart Start incluso | Italiano"
EXPECTED_PRICE=179
TARGET_PRICE=149
EXPECTED_WEEKS=24
EXPECTED_WORKOUTS=225
EXPECTED_NATIVE_WORKOUTS=189
EXPECTED_NOTES=30
ROOT=Path.home()/".local/state/ironman-operator"
BACKUP=ROOT/"beginner_price_679801_preflight_20261017.json"
ENDPOINT=f"/plans/v1/plans/{PLAN}"

class Stop(Exception): pass
def must(ok, reason):
    if not ok: raise Stop(reason)
def canonical(x):
    return json.dumps(x,sort_keys=True,ensure_ascii=False,default=str,separators=(",",":"))
def sig(x):
    return hashlib.sha256(canonical(x).encode()).hexdigest()

async def run():
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_COACH_ACCOUNT")
        async def detail():
            r=await c.get(ENDPOINT)
            must(not r.is_error and isinstance(r.data,dict),"PLAN_GET_FAILED")
            return r.data
        async def summaries():
            r=await c.get("/plans/v1/plans")
            must(not r.is_error and isinstance(r.data,list),"LIST_GET_FAILED")
            found=[x for x in r.data if x.get("planId")==PLAN]
            must(len(found)==1,"PLAN_LIST_IDENTITY_AMBIGUOUS")
            return found[0]
        before=await detail()
        summary=await summaries()
        must(before.get("planId")==PLAN and before.get("title")==TITLE,"PLAN_ID_TITLE_DRIFT")
        must(summary.get("title")==TITLE,"LIST_TITLE_DRIFT")
        must(before.get("isPublic") is True and summary.get("isPublic") is True,
             "PUBLICATION_NOT_CONFIRMED")
        must(before.get("weekCount")==EXPECTED_WEEKS and
             before.get("workoutCount")==EXPECTED_WORKOUTS and
             summary.get("workoutCount")==EXPECTED_WORKOUTS,
             "PLAN_WORKOUT_COUNT_DRIFT")
        must(before.get("planCategory")==4,"CATEGORY_CHANGED")
        must(before.get("price")==summary.get("price"),"DETAIL_LIST_PRICE_MISMATCH")
        if before.get("price")==TARGET_PRICE:
            print("ALREADY_149_NO_WRITES",json.dumps({"plan":PLAN,"price":TARGET_PRICE}))
            return 0
        must(before.get("price")==EXPECTED_PRICE,"PRICE_BASELINE_NOT_179")
        start=date.fromisoformat(str(before.get("startDate"))[:10])
        end=(start+timedelta(days=185)).isoformat()
        begin=start.isoformat()
        nr=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{begin}/{end}")
        must(not nr.is_error and isinstance(nr.data,list),"NOTES_READ_FAILED")
        n0=nr.data
        must(len(n0)==EXPECTED_NOTES,"NOTES_COUNT_DRIFT")
        wr=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{begin}/{end}")
        must(not wr.is_error and isinstance(wr.data,list),"WORKOUTS_READ_FAILED")
        w0=wr.data
        must(len(w0)==EXPECTED_NATIVE_WORKOUTS,"WORKOUTS_NATIVE_COUNT_DRIFT")
        nsha,wsha=sig(n0),sig(w0)
        must(not BACKUP.exists(),"EXISTING_PRICE_BACKUP_REVIEW_REQUIRED")
        ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
        # Private owner-only backup contains provider metadata and checksums,
        # never returned to ChatGPT or committed to GitHub.
        with BACKUP.open("x",encoding="utf-8") as f:
            BACKUP.chmod(0o600)
            json.dump({"plan":before,"notes_sha256":nsha,
                       "workouts_sha256":wsha},f,ensure_ascii=False,default=str)
            f.flush()
        print("PREFLIGHT_SAVED",json.dumps({"plan":PLAN,"old":EXPECTED_PRICE,
              "new":TARGET_PRICE,"weeks":EXPECTED_WEEKS,"workouts":len(w0),
              "notes":len(n0),"public":True}),flush=True)
        changed=await c._request("PUT",ENDPOINT,
                  json={"planId":PLAN,"price":TARGET_PRICE},_retry_on_401=False)
        # Always read provider even if PUT failed: ambiguous errors may commit.
        after=await detail()
        if changed.is_error or after.get("price")!=TARGET_PRICE:
            print("STOP_REVIEW_WRITE_RESULT_AMBIGUOUS",
                  json.dumps({"price_readback":after.get("price"),
                  "put_error":bool(changed.is_error)}),flush=True)
            return 3
        other_changed=[k for k in set(before)|set(after)
                       if k!="price" and not
                       ("modif" in k.lower() or "updat" in k.lower())
                       and before.get(k)!=after.get(k)]
        if other_changed:
            print("STOP_REVIEW_NON_PRICE_METADATA_CHANGED",
                  json.dumps({"fields":sorted(other_changed)}),flush=True)
            return 4
        nr2=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{begin}/{end}")
        wr2=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{begin}/{end}")
        must(not nr2.is_error and not wr2.is_error,"POST_WRITE_CALENDAR_READ_FAILED")
        must(sig(nr2.data)==nsha and sig(wr2.data)==wsha,"POST_WRITE_CALENDAR_DRIFT")
        listed=await summaries()
        must(listed.get("price")==TARGET_PRICE and listed.get("isPublic") is True,
             "POST_WRITE_LIST_PRICE_OR_VISIBILITY_DRIFT")
        print("PUBLIC_PRICE_149_VERIFIED",json.dumps({
            "plan":PLAN,"price":TARGET_PRICE,"old_price":EXPECTED_PRICE,
            "public":True,"workouts_preserved":len(w0),
            "native_notes_preserved":len(n0),"other_fields_changed":0}),flush=True)
        return 0

if __name__=="__main__":
    try: raise SystemExit(asyncio.run(run()))
    except Stop as exc:
        print("STOP_REVIEW",str(exc),flush=True)
        raise SystemExit(2)
