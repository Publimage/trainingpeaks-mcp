"""Independent final provider audit of public CHASING v1.2, 24 weeks."""
import asyncio,json,httpx,re
from collections import Counter
from datetime import date,timedelta
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
PLAN=685173;PERSON=6682479;OWNER=2116886
START=date(2027,1,4)
TARGET_MIN={9:720,10:940,11:990,16:820,17:955,19:1110,20:885,21:1200,22:950,23:620,24:215}
ST_DAYS={1:["LUN","VEN"],2:["MAR","VEN"],3:["MAR","VEN"],4:["MAR"],5:["LUN","VEN"],6:["LUN","VEN"],7:["LUN","VEN"]}
ST_DAYS.update({w:["LUN"] for w in range(8,17)})
ST_DAYS[17]=["VEN"]
ST_DAYS.update({w:["LUN"] for w in range(18,22)})
class Stop(Exception):pass
def need(x,m):
 if not x:raise Stop(m)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  need(isinstance(me,dict) and me.get("personId")==OWNER and not p.is_error,"OWNER_OR_PLAN")
  m=p.data
  need(m.get("planId")==PLAN and m.get("planPersonId")==PERSON and
       m.get("isPublic") is True and int(m.get("price") or 0)==199 and
       m.get("workoutCount")==276 and m.get("weekCount")==24 and
       "CHASING THE SLOT" in (m.get("title") or ""),"PLAN_SCOPE")
  rows=[]
  for first,last in [("2027-01-04","2027-02-28"),("2027-03-01","2027-04-25"),("2027-04-26","2027-06-20")]:
   v=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{first}/{last}")
   need(not v.is_error and isinstance(v.data,list),"WORKOUT_BLOCK_GET")
   rows.extend(v.data)
  need(len(rows)==249 and len({str(x.get("workoutId")) for x in rows})==249,"CLASSIC249")
  sport_count=Counter();totals=Counter();swims=[];tests=[]
  for x in rows:
   sp=x.get("workoutTypeValueId")
   need(sp in (1,2,3),"UNEXPECTED_SPORT")
   sport_count[sp]+=1
   w=(date.fromisoformat(str(x.get("workoutDay"))[:10])-START).days//7+1
   need(1<=w<=24,"DATE_OUT_OF_PLAN")
   mins=(x.get("totalTimePlanned") or 0)*60
   need(mins>0,"ZERO_DURATION_"+str(x.get("workoutId")))
   totals[w]+=mins
   structure=x.get("structure") or {}
   blocks=structure.get("structure") or []
   need(bool(blocks) and bool(structure.get("polyline")),"BUILDER_MISSING_"+str(x.get("workoutId")))
   for b in blocks:
    for st in b.get("steps") or []:
     if st.get("intensityClass") not in ("rest",):
      need(bool(st.get("targets")),"ACTIVE_TARGET_MISSING_"+str(x.get("workoutId")))
   if sp==1:
    swims.append((w,x))
    need((x.get("distancePlanned") or 0)>0,"SWIM_NATIVE_DISTANCE_ZERO")
    actual=0
    for b in blocks:
     reps=b.get("length",{}).get("value",1) if b.get("type")=="repetition" else 1
     for step in b.get("steps") or []:
      if step.get("length",{}).get("unit")=="meter":
       actual+=step["length"]["value"]*reps
    need(abs(actual-x["distancePlanned"])<.5,"SWIM_METER_DRIFT_"+str(x.get("workoutId")))
   if "test" in (x.get("title") or "").lower():
    tests.append({"week":w,"sport":sp,"id":x["workoutId"]})
  need(dict(sport_count)=={1:71,2:84,3:94},"SPORT_COUNTS")
  continuous=sorted(w for w,x in swims if "no-stop" in (x.get("title") or "").lower() or "continuati" in (x.get("title") or "").lower())
  need(continuous==[11,13,15,19],"FOUR_CONTINUOUS")
  swcounts=Counter(w for w,x in swims)
  need(all(swcounts[w]==(2 if w==24 else 3) for w in range(1,25)),"SWIM_WEEKLY_COUNTS")
  for week,target in TARGET_MIN.items():
   need(abs(totals[week]-target)<.01,f"W{week:02d}_ENDURANCE_BUDGET")
  def test_is(w,sp):
   return any(x["week"]==w and x["sport"]==sp for x in tests)
  need(all(test_is(17,k) for k in (1,2,3)),"W17_THREE_RETESTS_MISSING")
  _,token,error=await _access(c)
  need(not error and token,"NATIVE_STRENGTH_AUTH")
  strength=[]
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   for w in range(1,25):
    a=(START+timedelta(weeks=w-1)).isoformat()
    b=(START+timedelta(weeks=w-1,days=6)).isoformat()
    res=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/calendar/{PERSON}/{a}/{b}",headers=_headers(token))
    need(res.status_code==200 and isinstance(res.json(),list),"NATIVE_STRENGTH_WEEK_GET")
    week_events=res.json()
    got=sorted((date.fromisoformat(str(x.get("prescribedDate"))[:10])-START).days%7 for x in week_events)
    expected=sorted(("LUN","MAR","MER","GIO","VEN","SAB","DOM").index(y) for y in ST_DAYS.get(w,[]))
    need(got==expected,f"W{w:02d}_STRENGTH_DAY_DRIFT")
    strength.extend(week_events)
  need(len(strength)==27 and len({str(v.get("id")) for v in strength})==27,"NATIVE_STRENGTH_27")
  notes=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2027-01-04/2027-06-20")
  need(not notes.is_error and isinstance(notes.data,list) and len(notes.data)==31,"NATIVE_NOTES_31")
  start=next((n for n in notes.data if int(n.get("id") or n.get("calendarNoteId") or 0)==2664007),None)
  need(start is not None,"START_NOTE_MISSING")
  files={int(x["id"]):(str(x["fileName"]),int(x["contentLength"])) for x in start.get("attachments") or []}
  expect={97223:("CHASING_THE_SLOT_24W_Guida_Fueling_Nutrizione_v1.0.pdf",121278),
          98885:("CHASING_THE_SLOT_24W_Guida_Atleta_v1.2.pdf",41235),
          98886:("CHASING_THE_SLOT_24W_Guida_Settimana_per_Settimana_v1.2.pdf",72124)}
  need(files==expect,"GUIDES_THREE_ATTACHMENT_GATE")
  print(json.dumps({"stage":"CHASING_24W_FINAL_POSTFLIGHT_PASS","plan":PLAN,
     "classic":len(rows),"sports":{"swim":sport_count[1],"bike":sport_count[2],"run":sport_count[3]},
     "strength":len(strength),"total_workouts":276,"native_notes":31,
     "pdfs":[{"id":i,"name":v[0],"bytes":v[1]} for i,v in sorted(files.items())],
     "continuous_weeks":continuous,"retest_week17":[x for x in tests if x["week"]==17],
     "endurance_minutes":{str(k):round(totals[k]) for k in sorted(TARGET_MIN)},
     "public_preserved":True,"price_eur":199,"provider_writes":0,
     "athlete_calendar_writes":0,"workout_library_writes":0},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(main()))
 except Exception as e:
  print(json.dumps({"stage":"STOP_CHASING_24W_FINAL_POSTFLIGHT","reason":str(e)[:400],"provider_writes":0}),flush=True)
  raise
