"""CHASING W05 repair: remove product/week labels from plan workouts and make Sunday RUN long."""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
PLAN=685173; OWNER=2116886; PERSON=6682479; START="2027-02-01";END="2027-02-07"
CHANGES={4000954208:"Aerobico | 125' fondo sotto LT1",4000954310:"Lungo | 4h05 endurance sotto LT1"}
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w05_titles_longrun_fix_20261013.json"
def must(v,s):
 if not v:raise RuntimeError(s)
def stable(v):return {k:x for k,x in v.items() if k!="lastModifiedDate"}
def sha(v):return hashlib.sha256(json.dumps(v,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
async def snap(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_READ")
 h=p.data
 must(h.get("planId")==PLAN and h.get("planPersonId")==PERSON and h.get("isPublic") is False and h.get("workoutCount")==276,"PLAN_IDENTITY")
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
 must(not w.is_error and not n.is_error and len(w.data)==10,"BLOCK_COUNT")
 return w.data,sha(n.data)
async def main():
 async with TPClient() as c:
  user=await c._get_user_data()
  must(user.get("personId")==OWNER,"OWNER")
  rows,notes=await snap(c)
  base={x["workoutId"]:x for x in rows}; must(len(base)==10,"DUPLICATES")
  long=base[4000954242];short=base[4000954333]
  must(str(long["workoutDay"])[:10]=="2027-02-03" and long["title"]=="Steady | 85' 2x10' RPE4-5 con recupero 10'" and
       str(short["workoutDay"])[:10]=="2027-02-07" and abs(long["totalTimePlanned"]*60-85)<0.02 and
       abs(short["totalTimePlanned"]*60-20)<0.02,"RUN_PREFLIGHT")
  r=await c.get("/exerciselibrary/v2/libraries/3892602/items")
  must(not r.is_error and isinstance(r.data,list),"RUN_LIBRARY")
  t=next((x for x in r.data if x.get("exerciseLibraryItemId")==14947513),None)
  must(t is not None and t.get("itemName")=="Lungo | 85' facile" and isinstance(t.get("structure"),dict),"LONG_TEMPLATE")
  operations=[]
  for wid,title in CHANGES.items():
   v=base[wid]; must("CHASING W05" in v["title"],"TITLE_ALREADY_CHANGED")
   p=dict(v);p["title"]=title
   operations.append((wid,p))
  a=dict(long)
  for k,v in [("title","itemName"),("description","description"),("totalTimePlanned","totalTimePlanned"),("distancePlanned","distancePlanned"),("structure","structure"),("workoutSubTypeId","workoutSubTypeId")]:
   a[k]=t.get(v)
  a["workoutDay"]="2027-02-07"+str(long["workoutDay"])[10:]
  b=dict(short);b["workoutDay"]="2027-02-03"+str(short["workoutDay"])[10:]
  operations.extend([(4000954242,a),(4000954333,b)])
  must(not BACKUP.exists(),"BACKUP_EXISTS_CHECK_STATE")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":PLAN,"before":rows,"notes":notes},ensure_ascii=False,indent=2)+"\n")
  expected={i:stable(v) for i,v in base.items()}
  print(json.dumps({"stage":"PREFLIGHT_PASS","writes":len(operations)}))
  for wid,p in operations:
   before,ns=await snap(c);bm={x["workoutId"]:x for x in before}
   must(ns==notes and stable(bm[wid])==expected[wid],"PREWRITE_STATE_DRIFT")
   resp=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",json=p,_retry_on_401=False)
   after,ns2=await snap(c);am={x["workoutId"]:x for x in after}
   must(not resp.is_error and ns2==notes and len(am)==10 and stable(am[wid])==stable(p),"WRITE_VERIFY_FAILED")
   expected[wid]=stable(p)
   must(all(stable(am[i])==v for i,v in expected.items()),"OTHER_WORKOUT_DRIFT")
   print(json.dumps({"stage":"WRITE_VERIFIED","id":wid}))
  fin,_=await snap(c)
  total=round(sum((x.get("totalTimePlanned") or 0)*60 for x in fin))
  must(total==790,"W05_VOLUME_DRIFT")
  must(any(x["workoutId"]==4000954242 and str(x["workoutDay"])[:10]=="2027-02-07" and x["title"]=="Lungo | 85' facile" for x in fin),"SUNDAY_LONG_MISSING")
  print(json.dumps({"stage":"PASS_W05_CORRECTION","endurance_minutes":790,"private":True,"notes_intact":True,"other_workouts_intact":True}))
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","reason":str(e)[:300]}));raise
