"""Guarded calendar-date relocation of existing CHASING native Strength instances.

Do not recreate workouts; only update prescribedDate and title on the same ID.
Never write athlete calendar or workout libraries.
"""
import asyncio,copy,hashlib,json,httpx
from datetime import date,timedelta
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
PLAN=685173
PERSON=6682479
OWNER=2116886
BASE=date(2027,1,4)
DAYS=("LUN","MAR","MER","GIO","VEN","SAB","DOM")
CANARY_WEEKS=(19,)
REST_WEEKS=(1,5,6,7,8,9,10,11,12,13,14,15,16,17,18,20,21)
ALL_MOVE_WEEKS=set(CANARY_WEEKS+REST_WEEKS)
BASE_PATH="/rx/activity/v1"
class Stop(Exception):pass
def must(ok,why):
 if not ok:raise Stop(why)
def digest(x):
 return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(",",":"),default=str).encode()).hexdigest()
def dt(w,d):
 return (BASE+timedelta(weeks=w-1,days=d)).isoformat()
def week(w):
 return f"W{w:02d}"
def label(w,k,day):
 return f"CHASING THE SLOT | {week(w)} {day} | Forza {k}"
async def run(canary):
 selected=CANARY_WEEKS if canary else REST_WEEKS
 async with TPClient() as c:
  me=await c._get_user_data()
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  must(isinstance(me,dict) and me.get("personId")==OWNER and not p.is_error,"OWNER_OR_PLAN_READ")
  meta=p.data
  must(meta.get("planId")==PLAN and meta.get("planPersonId")==PERSON and
       meta.get("ownerPersonId")==OWNER and meta.get("isPublic") is True and
       meta.get("workoutCount")==276 and
       "CHASING THE SLOT" in (meta.get("title") or "") and
       "Advanced" in (meta.get("title") or ""),"PUBLIC_CHASING_PLAN_SCOPE")
  _,token,err=await _access(c)
  must(not err and token,"NO_STRENGTH_ACCESS")
  headers=_headers(token)
  async with httpx.AsyncClient(timeout=30,follow_redirects=False) as h:
   async def get_events():
    rows=[]
    for w in range(1,22):
     a=dt(w,0);b=dt(w,6)
     r=await h.get(STRENGTH_API_BASE+BASE_PATH+f"/workouts/calendar/{PERSON}/{a}/{b}",headers=headers)
     must(r.status_code==200 and isinstance(r.json(),list),"NATIVE_CALENDAR_READ_W"+str(w))
     rows.extend(r.json())
    must(len(rows)==27 and len({str(x.get("id")) for x in rows})==27,"NATIVE_27_ID_COUNT")
    return rows
   async def detail(id):
    r=await h.get(STRENGTH_API_BASE+BASE_PATH+"/workouts/"+str(id),headers=headers)
    must(r.status_code==200,"NATIVE_DETAIL_"+str(id))
    val=r.json().get("data") or {}
    must(str(val.get("id"))==str(id),"DETAIL_ID")
    return val
   events=await get_events()
   targets=[]
   for w in selected:
    src=dt(w,1);out=dt(w,4 if w==17 else 0)
    match=[x for x in events if (x.get("prescribedDate") or "")[:10]==src and
           ("| "+week(w)+" MAR |") in (x.get("title") or "")]
    must(len(match)==1,"SOURCE_NOT_UNIQUE_"+week(w))
    e=match[0]
    parts=(e.get("title") or "").split("Forza ")
    must(len(parts)==2 and parts[1] in ("A60","B60","D40","D45","M60","M45","M40","M35","M30"),"TITLE_BAD_"+week(w))
    labelNew=label(w,parts[1],"VEN" if w==17 else "LUN")
    must(not any((x.get("prescribedDate") or "")[:10]==out for x in events),"DEST_ST_NOT_EMPTY_"+week(w))
    old=await detail(e["id"])
    must(old.get("calendarId")==PERSON and
         (old.get("prescribedDate") or "")[:10]==src and
         old.get("title")==e.get("title") and
         old.get("workoutType")=="StructuredStrength" and
         len(old.get("blocks") or [])>=5 and
         (old.get("prescribedDurationInSeconds") or 0)>0,"NATIVE_SOURCE_DETAIL_DRIFT_"+week(w))
    targets.append({"week":w,"id":str(e["id"]),"from":src,"to":out,
                    "old_title":old["title"],"new_title":labelNew,"raw":old,
                    "blocks_sha":digest(old["blocks"]),
                    "seconds":old["prescribedDurationInSeconds"]})
   must(len(targets)==len(selected),"TARGET_COUNT")
   backup=Path.home()/".trainingpeaks-mcp"/("chasing_strength_relayout_20261022_canary.json" if canary else "chasing_strength_relayout_20261022_remaining.json")
   must(not backup.exists(),"BACKUP_EXISTS_STOP_NO_BLIND_RETRY")
   backup.parent.mkdir(parents=True,exist_ok=True)
   backup.write_text(json.dumps({"plan":PLAN,"kind":"canary" if canary else "remaining","targets":targets},ensure_ascii=False,default=str)+"\n")
   print(json.dumps({"stage":"PREFLIGHT_NATIVE_MOVE","count":len(targets),"weeks":list(selected),
     "plan":PLAN,"native_count":27,"backup":str(backup),"provider_writes":0}),flush=True)
   for i,t in enumerate(targets):
    current=await detail(t["id"])
    must(current.get("title")==t["old_title"] and (current.get("prescribedDate") or "")[:10]==t["from"] and
         digest(current.get("blocks"))==t["blocks_sha"] and
         current.get("prescribedDurationInSeconds")==t["seconds"],"MID_BATCH_DRIFT_W"+str(t["week"]))
    candidate=copy.deepcopy(current)
    candidate["prescribedDate"]=t["to"]
    candidate["title"]=t["new_title"]
    try:
     res=await h.post(STRENGTH_API_BASE+BASE_PATH+f"/plans/{PLAN}/workouts/save",json=candidate,headers=headers)
     http_status=res.status_code
    except httpx.RequestError:
     http_status=None
    # Inspect real state even when the transport is ambiguous. NEVER retry the POST blindly.
    after=await detail(t["id"])
    plan=await c.get(f"/plans/v1/plans/{PLAN}")
    must(http_status==200 and
         (after.get("prescribedDate") or "")[:10]==t["to"] and
         after.get("title")==t["new_title"] and
         digest(after.get("blocks"))==t["blocks_sha"] and
         after.get("prescribedDurationInSeconds")==t["seconds"] and
         after.get("calendarId")==PERSON and
         not plan.is_error and plan.data.get("workoutCount")==276 and
         plan.data.get("isPublic") is True,
         "NATIVE_MOVE_NOT_VERIFIED_W"+str(t["week"])+"_STOP")
    print(json.dumps({"stage":"NATIVE_STRENGTH_MOVE_VERIFIED","week":t["week"],"id":t["id"],
                      "from":t["from"],"to":t["to"],"total_completed":i+1}),flush=True)
   final=await get_events()
   for t in targets:
    by=[x for x in final if str(x.get("id"))==t["id"]]
    must(len(by)==1 and (by[0].get("prescribedDate") or "")[:10]==t["to"] and
         by[0].get("title")==t["new_title"],"FINAL_CALENDAR_MOVE_NOT_EXACT_W"+str(t["week"]))
   print(json.dumps({"stage":"CHASING_NATIVE_STRENGTH_RELAYOUT_PASS",
      "moved":len(targets),"native":len(final),"workouts":276,
      "athlete_calendar_writes":0,"library_writes":0,"public_preserved":True}),flush=True)
   return 0
