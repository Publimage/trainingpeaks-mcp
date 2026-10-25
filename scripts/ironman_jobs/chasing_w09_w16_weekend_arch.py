"""Guarded plan-only CHASING W09-W16 architected redistribution; do not touch athletes."""
import asyncio,json,hashlib
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
P=685173;OWNER=2116886;PERSON=6682479;LIB=3892601
START="2027-03-01";END="2027-04-25"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w09_w16_weekend_arch_20261013_backup.json"
# date moves preserve native structure, duration and identity
MOVES=[
(4001048428,9,2,6),(4001048457,9,6,2),
(4001050275,10,2,6),(4001050402,10,6,2),
(4001053067,11,5,6),(4001053081,11,5,6),(4001052988,11,2,5),(4001053014,11,6,2),
(4001055560,12,2,6),(4001055650,12,6,2),
(4001062330,14,6,4),(4001062150,14,2,6),(4001062213,14,3,2),
(4001065469,15,6,2),(4001065444,15,5,6),(4001065433,15,5,6),(4001065326,15,2,5),
(4001069070,16,2,6),(4001069271,16,6,2)
]
BIKES=[(4001065292,14975235,120,150),(4001065348,14975238,175,205)]
EXPECTED={9:890,10:915,11:900,12:735,13:1005,14:980,15:1200,16:805}
def must(q,s):
 if not q:raise RuntimeError(s)
def stable(v):return {k:x for k,x in v.items() if k!="lastModifiedDate"}
def sha(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def dt(w,d):return (date(2027,1,4)+timedelta(weeks=w-1,days=d)).isoformat()
def day(v):return str(v.get("workoutDay") or "")[:10]
async def read(c):
 p=await c.get(f"/plans/v1/plans/{P}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_GET")
 h=p.data
 must(h.get("planId")==P and h.get("planPersonId")==PERSON and h.get("isPublic") is False and
      h.get("price") in (None,0) and h.get("workoutCount")==276,"PLAN_SCOPE")
 a=await c.get(f"/plans/v1/plans/{P}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{P}/calendarNote/{START}/{END}")
 must(not a.is_error and not n.is_error and isinstance(a.data,list) and
      isinstance(n.data,list) and len(a.data)==82,"W09_W16_SCOPE_COUNT")
 must(len({x.get("workoutId") for x in a.data})==82,"DUPLICATE_ID")
 return a.data,sha(n.data)
async def main():
 async with TPClient() as c:
  u=await c._get_user_data();must(u.get("personId")==OWNER,"OWNER_SCOPE")
  original,notes=await read(c)
  byid={v["workoutId"]:v for v in original}
  lib=await c.get(f"/exerciselibrary/v2/libraries/{LIB}/items")
  must(not lib.is_error and isinstance(lib.data,list),"LIBRARY_UNREADABLE")
  templates={v.get("exerciseLibraryItemId"):v for v in lib.data}
  steps=[]
  for wid,tid,old,new in BIKES:
   a=byid[wid];t=templates.get(tid)
   must(t is not None and a.get("workoutTypeValueId")==2 and
        abs(a["totalTimePlanned"]*60-old)<0.03 and
        abs(t["totalTimePlanned"]*60-new)<0.03 and
        isinstance(t.get("structure"),dict) and
        "CHASING" not in t.get("itemName","") and
        t.get("itemName","").count("|")==1,"BIKE_PREFLIGHT")
   p=dict(a)
   for k,v in (("title","itemName"),("description","description"),
               ("totalTimePlanned","totalTimePlanned"),("distancePlanned","distancePlanned"),
               ("structure","structure"),("workoutSubTypeId","workoutSubTypeId")):p[k]=t.get(v)
   steps.append((wid,p,"bike_template"))
  for wid,week,old,new in MOVES:
   a=byid.get(wid)
   must(a is not None and day(a)==dt(week,old),"MOVE_SOURCE_MISMATCH_"+str(wid))
   must(a["workoutTypeValueId"]==(2 if wid in (4001053067,4001062330,4001065469,4001065433) else 3),
        "SPORT_MISMATCH_"+str(wid))
   p=dict(a);p["workoutDay"]=dt(week,new)+str(a["workoutDay"])[10:]
   steps.append((wid,p,"day_move"))
  must(len(steps)==21 and len({s[0] for s in steps})==21,"CHANGE_COUNT")
  must(not BACKUP.exists(),"BACKUP_EXISTS_VERIFY_STATE_FIRST")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":P,"before":original,"notes_hash":notes,
     "modifications":[{"id":i,"kind":a} for i,_,a in steps]},ensure_ascii=False,indent=2)+"\n")
  expected={wid:stable(v) for wid,v in byid.items()}
  print(json.dumps({"stage":"PREFLIGHT_PASS","plan":P,"range":"W09-W16","writes":len(steps)}),flush=True)
  for i,(wid,payload,kind) in enumerate(steps):
   live,ns=await read(c);lm={x["workoutId"]:x for x in live}
   must(ns==notes and sorted(lm)==sorted(byid) and stable(lm[wid])==expected[wid],"PREWRITE_DRIFT_"+str(wid))
   resp=await c._request("PUT",f"/plans/v1/plans/{P}/workouts/{wid}",json=payload,_retry_on_401=False)
   fresh,ns2=await read(c);fm={x["workoutId"]:x for x in fresh}
   must(not resp.is_error and ns2==notes and stable(fm[wid])==stable(payload),"WRITE_NOT_VERIFIED_"+str(wid))
   expected[wid]=stable(payload)
   must(all(stable(fm[k])==v for k,v in expected.items()),"UNEXPECTED_CHANGE_"+str(wid))
   print(json.dumps({"stage":"WRITE_VERIFIED","number":i+1,"workout_id":wid,"type":kind}),flush=True)
  z,_=await read(c)
  totals={w:round(sum(x.get("totalTimePlanned",0)*60 for x in z if dt(w,0)<=day(x)<=dt(w,6))) for w in range(9,17)}
  must(totals==EXPECTED,"VOLUME_MISMATCH_"+str(totals))
  must(all("CHASING W" not in x.get("title","") for x in z),"PLAN_TITLE_WEEK_LABEL")
  print(json.dumps({"stage":"PASS_W09_W16","minutes":totals,"count":82,"week13_sunday_off":True,
       "unchanged_ids":True,"notes_preserved":True,"plan_private":True,"athlete_untouched":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","error":str(e)[:300]}),flush=True);raise
