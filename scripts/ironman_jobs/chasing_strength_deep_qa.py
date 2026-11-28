"""Read-only deep native Strength structure and duration QA for CHASING 24W."""
import asyncio,json,httpx
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
PERSON=6682479
TEMPLATES={"A60":"330618","B60":"330621","M60":"330624","D40":"330626","D45":"330626","M45":"330628","M40":"330628","M35":"330629","M30":"330629"}
def sig(w):
 return [[{"exercise":(p.get("exercise") or {}).get("title"),"sets":len(p.get("sets") or [])} for p in b.get("prescriptions") or []] for b in w.get("blocks") or []]
async def main():
 ledger=json.loads(Path("data/chasing_24w_day_ledger_20261012.json").read_text())
 expected={}
 for w in ledger["weeks"]:
  for d,day in enumerate(w["days"]):
   if day.get("ST"):
    dt=(date(2027,1,4)+timedelta(weeks=w["week"]-1,days=d)).isoformat()
    expected[dt]=(day["strength_template"],day["ST"])
 async with TPClient() as c:
  u=await c._get_user_data()
  if u.get("personId")!=2116886:return 2
  _,token,err=await _access(c)
  if err:return 3
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   headers=_headers(token)
   rr=await h.get(STRENGTH_API_BASE+"/rx/activity/v1/libraryContent/workoutLibrary/3894341",headers=headers)
   if rr.status_code!=200:return 4
   v=rr.json();items=v.get("data",v) if isinstance(v,dict) else v
   lib={str(x.get("id")):x.get("workout") or {} for x in items if isinstance(x,dict)}
   issues=[];checked=0
   for week in range(1,22):
    a=(date(2027,1,4)+timedelta(weeks=week-1)).isoformat()
    b=(date(2027,1,4)+timedelta(weeks=week)).isoformat()
    cr=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/calendar/{PERSON}/{a}/{b}",headers=headers)
    if cr.status_code!=200:return 5
    for x in cr.json():
     dt=(x.get("prescribedDate") or "")[:10]
     if dt not in expected:
      issues.append({"date":dt,"issue":"unexpected"});continue
     k,minutes=expected[dt]
     dr=await h.get(STRENGTH_API_BASE+"/rx/activity/v1/workouts/"+str(x.get("id")),headers=headers)
     if dr.status_code!=200:
      issues.append({"date":dt,"issue":"detail_unavailable"});continue
     w=dr.json().get("data") or {}
     ref=lib[TEMPLATES[k]]
     if sig(w)!=sig(ref):issues.append({"date":dt,"issue":"exercise_or_sets_drift"})
     if w.get("prescribedDurationInSeconds")!=minutes*60:issues.append({"date":dt,"issue":"duration_drift","got":w.get("prescribedDurationInSeconds"),"expected":minutes*60})
     if w.get("calendarId")!=PERSON:issues.append({"date":dt,"issue":"wrong_calendar"})
     checked+=1
   print(json.dumps({"stage":"NATIVE_STRENGTH_DEEP_QA","expected":len(expected),"checked":checked,"issues":issues[:30],"pass":checked==len(expected) and not issues},ensure_ascii=False),flush=True)
   return 0 if checked==len(expected) and not issues else 6
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
