"""Guarded recovery Coach Notes propagation to EXISTING CHASING private native
Strength Builder Training Plan workouts. Library is NOT auto-propagated.
No workout recreation, no athlete calendar, no top-level duration changes.
"""
import asyncio,json,copy,httpx
from datetime import date,timedelta
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
from chasing_strength_rests_common import REST,MARKER,apply,assert_correct
OWNER=2116886;PERSON=6682479;PLAN=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
ANCHOR=date(2027,1,4)
LEDGER=Path("data/chasing_24w_day_ledger_20261012.json")
BASE="/rx/activity/v1"
EXT={"D45":"D40","M35":"M30","M40":"M45"}
DAYS=["LUN","MAR","MER","GIO","VEN","SAB","DOM"]
def must(b,reason):
 if not b:raise RuntimeError(reason)
def d(week,day):return (ANCHOR+timedelta(weeks=week-1,days=day)).isoformat()
def expected(first,last):
 weeks=json.loads(LEDGER.read_text())["weeks"]
 assert len(weeks)==24
 rows=[]
 for w in weeks:
  week=w["week"]
  if week<first or week>last:continue
  for day,v in enumerate(w["days"]):
   if not v.get("ST"):continue
   k=v["strength_template"]
   true_key=EXT.get(k,k)
   must(true_key in REST,f"UNMAPPED_STRENGTH_{k}")
   rows.append({"day":d(week,day),"week":week,"key":k,"rest_key":true_key,
      "title":f"CHASING THE SLOT | W{week:02d} {DAYS[day]} | Forza {k}","minutes":v["ST"]})
 return rows
async def run(first,last):
 must((first,last) in {(1,8),(9,16),(17,21)},"BLOCK_SCOPE_NOT_ALLOWED")
 rows=expected(first,last)
 must(len(rows)=={(1,8):14,(9,16):8,(17,21):5}[(first,last)],"LEDGER_COUNT_DRIFT")
 back=Path.home()/f".trainingpeaks-mcp/chasing_strength_rest_plan_{first:02d}_{last:02d}_backup.json"
 async with TPClient() as c:
  user=await c._get_user_data()
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  must(isinstance(user,dict) and user.get("personId")==OWNER and not p.is_error,
       "OWNER_OR_PLAN_READ_FAILED")
  m=p.data
  must(m.get("planId")==PLAN and m.get("planPersonId")==PERSON and
       m.get("ownerPersonId")==OWNER and m.get("isPublic") is False and
       m.get("title")==TITLE and m.get("workoutCount")==276 and
       str(m.get("startDate") or "")[:10]==ANCHOR.isoformat(),"PLAN_SCOPE_DRIFT")
  _,token,error=await _access(c)
  must(not error and token,"NATIVE_ACCESS_FAILED")
  headers=_headers(token)
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   a=d(first,0);b=d(last,6)
   rr=await h.get(STRENGTH_API_BASE+BASE+f"/workouts/calendar/{PERSON}/{a}/{b}",headers=headers)
   must(rr.status_code==200 and isinstance(rr.json(),list),"STRENGTH_CALENDAR_GET_FAIL")
   events=rr.json()
   must(len(events)==len(rows),"CALENDAR_STRENGTH_COUNT_DRIFT")
   entries={}
   for row in rows:
    matches=[x for x in events if (x.get("prescribedDate") or "")[:10]==row["day"]
            and x.get("title")==row["title"]]
    must(len(matches)==1,f"TARGET_SLOT_NOT_UNIQUE_W{row['week']}")
    row["id"]=str(matches[0].get("id"))
    must(row["id"] and row["id"]!="None","NATIVE_ID_MISSING")
   must(len({x["id"] for x in rows})==len(rows),"DUPLICATE_STRENGTH_ID")
   async def detail(id):
    r=await h.get(STRENGTH_API_BASE+BASE+f"/workouts/{id}",headers=headers)
    must(r.status_code==200,"NATIVE_DETAIL_GET_FAILED")
    return r.json().get("data") or {}
   for row in rows:
    original=await detail(row["id"])
    must(str(original.get("id"))==row["id"] and original.get("title")==row["title"] and
         original.get("calendarId")==PERSON and (original.get("prescribedDate") or "")[:10]==row["day"] and
         original.get("workoutType")=="StructuredStrength" and
         original.get("prescribedDurationInSeconds")==row["minutes"]*60,
         "STRENGTH_DETAIL_ID_OR_DURATION_DRIFT")
    must(all(MARKER not in str(q.get("coachNotes") or "") for v in original.get("blocks") or []
         for q in v.get("prescriptions") or []),"REST_ALREADY_PRESENT_NO_REPEAT")
    apply(original,row["rest_key"])
    entries[row["id"]]=original
   must(not back.exists(),"BLOCK_BACKUP_EXISTS_NO_BLIND_RETRY")
   back.parent.mkdir(parents=True,exist_ok=True)
   back.write_text(json.dumps({"plan":PLAN,"weeks":[first,last],"rows":rows,"original_workouts":entries},
                        ensure_ascii=False,indent=2)+"\n")
   print(json.dumps({"stage":"PREFLIGHT_PASS","weeks":[first,last],"count":len(rows),
       "notes_only":True,"planned_duration_changed":False}),flush=True)
   done=0
   for row in rows:
    before=entries[row["id"]]
    current=await detail(row["id"])
    must(current.get("title")==before.get("title") and
         current.get("prescribedDurationInSeconds")==before.get("prescribedDurationInSeconds") and
         all(MARKER not in str(q.get("coachNotes") or "") for b in current.get("blocks") or []
             for q in b.get("prescriptions") or []),
         "MID_BLOCK_DRIFT_STOP")
    candidate=apply(current,row["rest_key"])
    result=await h.post(STRENGTH_API_BASE+BASE+f"/plans/{PLAN}/workouts/save",
                  json=candidate,headers=headers)
    now=await detail(row["id"])
    must(result.status_code==200,"NATIVE_EXISTING_SAVE_FAILED_STOP_NO_RETRY")
    assert_correct(current,now,row["rest_key"])
    must(now.get("prescribedDurationInSeconds")==before.get("prescribedDurationInSeconds") and
         now.get("title")==before.get("title"),"TITLE_OR_DURATION_DRIFT")
    done+=1
    print(json.dumps({"stage":"STRENGTH_REST_NOTE_VERIFIED","id":row["id"],
          "week":row["week"],"variant":row["key"],"duration_unchanged":True}),flush=True)
   m2=await c.get(f"/plans/v1/plans/{PLAN}")
   must(not m2.is_error and m2.data.get("workoutCount")==276 and m2.data.get("isPublic") is False,
        "PLAN_COUNT_OR_PRIVACY_CHANGED")
   print(json.dumps({"stage":"STRENGTH_REST_PLAN_BLOCK_PASS","weeks":[first,last],
         "modified":done,"total_plan_workouts":276,"notes_only":True,
         "no_athlete_calendar":True,"no_duration_changes":True}),flush=True)
   return 0
