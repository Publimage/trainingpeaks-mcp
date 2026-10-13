"""CHASING W05-W08 latest coach-approved plan patch. Plan-only, 8 in-place PUTs."""
import asyncio,json,hashlib
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
OWNER=2116886
PERSON=6682479
PLAN=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
START="2027-02-01"
END="2027-02-28"
LIB=3892601
BIKES=[
 (4000954208,14975291,105,125,"Aerobico | 105' fondo sotto LT1"),
 (4000954310,14975323,220,245,"Lungo | 3h40 endurance sotto LT1")
]
SWAPS=[
 (6,4000966424,70,4000966636,30),
 (7,4000972947,75,4000973000,40),
 (8,4001046357,65,4001046452,35)
]
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w05_w08_latest_20261013_backup.json"
def must(x,msg):
 if not x: raise RuntimeError(msg)
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def stable(x):return {k:v for k,v in x.items() if k!="lastModifiedDate"}
def day(x):return str(x.get("workoutDay") or "")[:10]
def dayfor(w,offset):return (date(2027,1,4)+timedelta(weeks=w-1,days=offset)).isoformat()
async def snapshot(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_READ_FAILED")
 h=p.data
 must(h.get("planId")==PLAN and h.get("planPersonId")==PERSON and
      h.get("title")==TITLE and h.get("isPublic") is False and
      h.get("price") in (None,0) and h.get("workoutCount")==276 and
      str(h.get("startDate") or "")[:10] in ("2027-01-04","2027-01-05"),"PLAN_SCOPE_DRIFT")
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
 must(not w.is_error and not n.is_error and isinstance(w.data,list) and
      isinstance(n.data,list) and len(w.data)==40,"W05_W08_SCOPE_OR_COUNT_CHANGED")
 ids=[v.get("workoutId") for v in w.data]
 must(all(type(i) is int for i in ids) and len(ids)==len(set(ids)),"WORKOUT_ID_DUPLICATION")
 return w.data,digest(n.data)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(isinstance(me,dict) and me.get("personId")==OWNER,"COACH_OWNER_MISMATCH")
  original,notes=await snapshot(c)
  before={w["workoutId"]:w for w in original}
  lib=await c.get(f"/exerciselibrary/v2/libraries/{LIB}/items")
  must(not lib.is_error and isinstance(lib.data,list),"BIKE_LIBRARY_READ_FAILED")
  templates={v.get("exerciseLibraryItemId"):v for v in lib.data}
  operations=[]
  for wid,tid,old,new,title in BIKES:
   w=before.get(wid);t=templates.get(tid)
   must(w is not None and t is not None,"BIKE_SOURCE_OR_TEMPLATE_MISSING")
   must(w.get("workoutTypeValueId")==2 and w.get("title")==title and
        abs((w.get("totalTimePlanned") or 0)*60-old)<0.02 and
        abs((t.get("totalTimePlanned") or 0)*60-new)<0.02 and
        isinstance(t.get("structure"),dict),"BIKE_PREFLIGHT_FAILED")
   must(day(w)==(dayfor(5,1) if wid==4000954208 else dayfor(5,5)),"BIKE_DATE_MISMATCH")
   patch=dict(w)
   for x,y in (("title","itemName"),("description","description"),("totalTimePlanned","totalTimePlanned"),
               ("distancePlanned","distancePlanned"),("structure","structure"),("workoutSubTypeId","workoutSubTypeId")):
    patch[x]=t.get(y)
   operations.append((wid,patch,"bike_replace"))
  for week,longid,longmin,shortid,shortmin in SWAPS:
   long=before.get(longid);short=before.get(shortid)
   must(long is not None and short is not None and long.get("workoutTypeValueId")==3 and
        short.get("workoutTypeValueId")==3 and
        abs((long.get("totalTimePlanned") or 0)*60-longmin)<0.02 and
        abs((short.get("totalTimePlanned") or 0)*60-shortmin)<0.02 and
        day(long)==dayfor(week,2) and day(short)==dayfor(week,6),
        f"RUN_SWAP_PREFLIGHT_W{week}")
   l=dict(long);s=dict(short)
   l["workoutDay"]=dayfor(week,6)+str(long["workoutDay"])[10:]
   s["workoutDay"]=dayfor(week,2)+str(short["workoutDay"])[10:]
   operations.extend([(longid,l,"long_to_sunday"),(shortid,s,"easy_to_wednesday")])
  must(len(operations)==8,"BAD_OPERATION_COUNT")
  must(not BACKUP.exists(),"BACKUP_EXISTS_RECONCILE_BEFORE_RETRY")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":PLAN,"source":original,"notes_sha256":notes,
      "planned": [{"id":wid,"action":action} for wid,_,action in operations]},ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"PREFLIGHT_PASS","plan":PLAN,"scope":"W05-W08","writes":8,"backup":str(BACKUP)}),flush=True)
  expected={wid:stable(w) for wid,w in before.items()}
  ids=sorted(before)
  for i,(wid,payload,action) in enumerate(operations):
   live,ns=await snapshot(c)
   lmap={w["workoutId"]:w for w in live}
   must(ns==notes and sorted(lmap)==ids and stable(lmap[wid])==expected[wid],
        f"WRITE_PRECONDITION_CHANGED_{wid}")
   res=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",
                         json=payload,_retry_on_401=False)
   after,an=await snapshot(c)
   amap={w["workoutId"]:w for w in after}
   intended=stable(payload)
   must(not res.is_error and sorted(amap)==ids and an==notes and
        stable(amap[wid])==intended,f"WRITE_NOT_VERIFIED_{wid}_STOP")
   expected[wid]=intended
   for ident,exp in expected.items():
    must(stable(amap[ident])==exp,f"UNEXPECTED_WORKOUT_DRIFT_{ident}")
   print(json.dumps({"stage":"WRITE_VERIFIED","number":i+1,"id":wid,"change":action}),flush=True)
  done,_=await snapshot(c)
  mapped={z["workoutId"]:z for z in done}
  minutes={}
  for week in range(5,9):
   start=dayfor(week,0);end=dayfor(week,6)
   minutes[week]=sum(round((z.get("totalTimePlanned") or 0)*60) for z in done
                     if start<=day(z)<=end)
  must(minutes=={5:790,6:850,7:825,8:710},f"ENDURANCE_TOTAL_DRIFT_{minutes}")
  print(json.dumps({"stage":"PASS_CHASING_W05_W08","endurance_minutes":minutes,
     "all_40_workout_ids_unchanged":True,"native_content_verification":True,
     "all_notes_preserved":True,"private":True,"athlete_calendars_untouched":True}),flush=True)
if __name__=="__main__":
 try: asyncio.run(main())
 except Exception as exc:
  print(json.dumps({"stage":"STOP_NO_BLIND_RETRY","reason":str(exc)[:300]}),flush=True)
  raise
