"""Independent read-only final recovery-note coverage audit for native
CHASING 7 Strength Builder library models and 27 private plan copies.
"""
import asyncio,json,httpx
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
from chasing_strength_rests_common import REST,LIB_ID,MARKER
OWNER=2116886;PLAN=685173;PERSON=6682479;LIB=3894341
ANCHOR=date(2027,1,4)
LEDGER=Path("data/chasing_24w_day_ledger_20261012.json")
EXT={"D45":"D40","M35":"M30","M40":"M45"}
def must(v,s):
 if not v:raise RuntimeError(s)
def audit(w,key):
 blocks=w.get("blocks") or []
 if len(blocks)!=len(REST[key])+1 or blocks[0].get("blockType")!="WarmUp":
  return False,0
 checks=0
 for b in blocks:
  for p in b.get("prescriptions") or []:
   note=p.get("coachNotes") or ""
   if MARKER not in note or "RECUPERI OPERATIVI" not in note:return False,checks
   checks+=1
 return True,checks
def iso(week,day):return (ANCHOR+timedelta(weeks=week-1,days=day)).isoformat()
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  must(isinstance(u,dict) and u.get("personId")==OWNER and not p.is_error,"OWNER_OR_PLAN")
  must(p.data.get("planId")==PLAN and p.data.get("planPersonId")==PERSON and
       p.data.get("isPublic") is False and p.data.get("workoutCount")==276,"PLAN_DRIFT")
  _,token,err=await _access(c)
  must(not err and token,"NATIVE_TOKEN")
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   headers=_headers(token)
   r=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/libraryContent/workoutLibrary/{LIB}",headers=headers)
   must(r.status_code==200,"LIBRARY_GET")
   raw=r.json();items=raw if isinstance(raw,list) else raw.get("data") or []
   must(len(items)==7 and {str(x.get("id")) for x in items}==set(LIB_ID.values()),"LIB_IDS")
   libcount=0
   for key,id in LIB_ID.items():
    w=next(x for x in items if str(x["id"])==id)["workout"]
    ok,n=audit(w,key)
    must(ok and w.get("calendarId") is None and w.get("prescribedDate") is None and
         w.get("prescribedDurationInSeconds") is None,"LIB_REST_OR_DURATION")
    libcount+=n
   ledger=json.loads(LEDGER.read_text())["weeks"]
   must(len(ledger)==24,"LEDGER")
   expected={}
   for v in ledger:
    for j,s in enumerate(v["days"]):
     if s.get("ST"):
      expected[iso(v["week"],j)]=(EXT.get(s["strength_template"],s["strength_template"]),s["ST"])
   must(len(expected)==27,"LEDGER_STRENGTH_COUNT")
   events=[]
   for w in range(1,22,4):
    a=iso(w,0);b=iso(min(w+3,21),6)
    res=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/calendar/{PERSON}/{a}/{b}",headers=headers)
    must(res.status_code==200 and isinstance(res.json(),list),f"PLAN_CALENDAR_{w}")
    events.extend(res.json())
   must(len(events)==27 and len({str(x.get("id")) for x in events})==27,"PLAN_STRENGTH_IDS")
   planchecks=0
   for x in events:
    dt=(x.get("prescribedDate") or "")[:10]
    must(dt in expected,"UNEXPECTED_STRENGTH_DATE")
    key,minutes=expected[dt]
    rr=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/{x['id']}",headers=headers)
    must(rr.status_code==200,"DETAIL_GET_FAIL")
    w=rr.json().get("data") or {}
    ok,n=audit(w,key)
    must(ok and w.get("calendarId")==PERSON and
         w.get("prescribedDurationInSeconds")==minutes*60,
         f"PLAN_NOTES_OR_DURATION_DRIFT_{dt}")
    planchecks+=n
   print(json.dumps({"stage":"STRENGTH_RECOVERY_GLOBAL_READBACK_PASS",
       "library_models":7,"library_exercise_note_fields":libcount,
       "plan_instances":27,"plan_exercise_note_fields":planchecks,
       "total_training_plan_workouts":276,"library_duration_fields_added":0,
       "plan_duration_fields_changed":0,"read_only":True,
       "missing_rest_notes":0,"athlete_calendar_writes":0},ensure_ascii=False),flush=True)
   return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(main()))
 except Exception as exc:
  print(json.dumps({"stage":"STOP_QA","reason":str(exc)[:210]},ensure_ascii=False),flush=True)
  raise
