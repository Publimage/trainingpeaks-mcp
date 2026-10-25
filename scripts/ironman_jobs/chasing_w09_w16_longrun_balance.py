"""CHASING W09-16 RUN long restoration; native reused library templates, weekly volume preserved."""
import asyncio,json,hashlib
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
OWNER=2116886;PERSON=6682479;PLAN=685173;START="2027-03-01";END="2027-04-25"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w09_16_longrun_balanced_20261013.json"
RUNS=[
 (9,4001048428,85,100,14947553),
 (10,4001050275,95,105,14947566),
 (11,4001052988,70,110,14947567),
 (12,4001055560,65,80,14947558),
 (13,4001059005,100,110,14947567),
 (14,4001062150,95,120,14976434),
 (15,4001065326,90,130,14976435),
 (16,4001069070,80,90,14947576)]
BIKES=[
 (9,4001048384,130,115,14976436),
 (10,4001050247,130,120,14976437),
 (11,4001052939,135,95,14976438),
 (12,4001055505,110,95,14976439),
 (13,4001059223,290,280,14976441),
 (14,4001062280,240,215,14976442),
 (15,4001065469,140,100,14976443),
 (16,4001069047,120,110,14976444)]
TOTAL={9:890,10:915,11:900,12:735,13:1005,14:980,15:1200,16:805}
def must(q,s):
 if not q:raise RuntimeError(s)
def clean(v):return {k:x for k,x in v.items() if k!="lastModifiedDate"}
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
def dt(w,d):return (date(2027,1,4)+timedelta(weeks=w-1,days=d)).isoformat()
def day(v):return str(v.get("workoutDay") or "")[:10]
async def snapshot(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_READ")
 h=p.data
 must(h.get("planId")==PLAN and h.get("planPersonId")==PERSON and h.get("isPublic") is False and h.get("price") in (None,0) and h.get("workoutCount")==276,"PLAN_SCOPE")
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
 must(not w.is_error and not n.is_error and len(w.data)==82 and len({i["workoutId"] for i in w.data})==82,"BLOCK_READ_COUNT")
 return w.data,digest(n.data)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(me.get("personId")==OWNER,"WRONG_OWNER")
  before,notes=await snapshot(c);base={x["workoutId"]:x for x in before}
  libs={}
  for libid in (3892601,3892602):
   r=await c.get(f"/exerciselibrary/v2/libraries/{libid}/items")
   must(not r.is_error and isinstance(r.data,list),"LIB_READ_FAILED")
   libs[libid]={x.get("exerciseLibraryItemId"):x for x in r.data}
  ops=[]
  def template_edit(week,wid,old,new,tid,libid):
   x=base[wid];t=libs[libid].get(tid)
   must(t is not None and x.get("workoutTypeValueId")== (3 if libid==3892602 else 2)
      and abs((x.get("totalTimePlanned") or 0)*60-old)<0.02
      and abs((t.get("totalTimePlanned") or 0)*60-new)<0.02
      and isinstance(t.get("structure"),dict)
      and t["itemName"].count("|")==1 and "CHASING" not in t["itemName"]
      and not any("W"+str(week) in t["itemName"] for _ in range(1)),f"TEMPLATE_MISMATCH_{wid}")
   y=dict(x)
   for k,key in (("title","itemName"),("description","description"),("totalTimePlanned","totalTimePlanned"),
                 ("distancePlanned","distancePlanned"),("structure","structure"),("workoutSubTypeId","workoutSubTypeId")):
    y[k]=t.get(key)
   if week==13 and libid==3892602:
    must(day(x)==dt(week,2),"W13_LONG_NOT_WED")
    y["workoutDay"]=dt(week,6)+str(x["workoutDay"])[10:]
   ops.append((wid,y))
  for week,wid,old,new,tid in BIKES:template_edit(week,wid,old,new,tid,3892601)
  for week,wid,old,new,tid in RUNS:template_edit(week,wid,old,new,tid,3892602)
  # Restore W13 Wednesday low-cost running without new workout (Thursday easy run moves to Wednesday).
  x=base[4001059124]
  must(x.get("workoutTypeValueId")==3 and day(x)==dt(13,3) and abs(x["totalTimePlanned"]*60-50)<0.02,"W13_EASY_CONFLICT")
  y=dict(x);y["workoutDay"]=dt(13,2)+str(x["workoutDay"])[10:];ops.append((4001059124,y))
  # Previous test slot label is contextual; remove from title only.
  t=base[4001048397]
  must(t["title"]=="Test | RETEST W09 | T1500 - 2500 m","TEST_TITLE_DRIFT")
  test=dict(t);test["title"]="Test | T1500 - 2500 m";ops.append((4001048397,test))
  must(len(ops)==18 and len({i for i,_ in ops})==18,"OPS_COUNT")
  must(not BACKUP.exists(),"BACKUP_EXISTS_RECONCILE")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":PLAN,"before":before,"notes_digest":notes,
         "updates":[i for i,_ in ops]},ensure_ascii=False,indent=2)+"\n")
  expected={wid:clean(x) for wid,x in base.items()}
  print(json.dumps({"stage":"PREFLIGHT_PASS","operations":18,"backup":str(BACKUP)}),flush=True)
  for idx,(wid,patch) in enumerate(ops):
   current,ns=await snapshot(c);m={x["workoutId"]:x for x in current}
   must(ns==notes and clean(m[wid])==expected[wid],"PREWRITE_CONFLICT_"+str(wid))
   r=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",json=patch,_retry_on_401=False)
   after,ns=await snapshot(c);m={x["workoutId"]:x for x in after}
   must(not r.is_error and ns==notes and clean(m[wid])==clean(patch),"WRITE_UNVERIFIED_"+str(wid))
   expected[wid]=clean(patch)
   must(all(clean(m[i])==q for i,q in expected.items()),"OTHER_WORKOUT_CHANGED")
   print(json.dumps({"stage":"VERIFIED","n":idx+1,"id":wid}),flush=True)
  done,ns=await snapshot(c)
  totals={w:round(sum((x.get("totalTimePlanned") or 0)*60 for x in done if dt(w,0)<=day(x)<=dt(w,6))) for w in range(9,17)}
  must(totals==TOTAL,"VOLUME_DRIFT_"+str(totals))
  longmax={w:max(round(x.get("totalTimePlanned",0)*60) for x in done if dt(w,0)<=day(x)<=dt(w,6) and x.get("workoutTypeValueId")==3) for w in range(9,17)}
  must(longmax=={9:100,10:105,11:110,12:80,13:110,14:120,15:130,16:90},"RUN_LONG_MISMATCH_"+str(longmax))
  must(any(day(x)==dt(13,6) and x.get("workoutTypeValueId")==3 and abs(x["totalTimePlanned"]*60-110)<.02 for x in done),"W13_SUN_LONG_MISSING")
  print(json.dumps({"stage":"PASS_W09_W16_LONGRUN_QA","minutes":totals,"long_minutes":longmax,"count":82,"notes_preserved":True,"plan_private":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as exc:
  print(json.dumps({"stage":"STOP_RECONCILE","error":str(exc)[:350]}),flush=True);raise
