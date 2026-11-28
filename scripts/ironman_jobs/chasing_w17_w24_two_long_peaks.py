"""Plan-only W17-W24: two 150min run peaks, recovery, W19 rehearsal, taper."""
import asyncio,json,hashlib
from datetime import date,timedelta
from pathlib import Path
from tp_mcp.client import TPClient
PLAN=685173;OWNER=2116886;PERSON=6682479
START="2027-04-26";END="2027-06-20"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w17_w24_two_long_peaks_20261013.json"
# id, library, template id, expected old minutes, expected new minutes
TEMPLATES=[
(4001071997,3892602,14976477,85,150),
(4001072016,3892601,14976481,170,145),
(4001072083,3892601,14976482,290,250),
(4001074490,3892602,14976434,85,120),
(4001074565,3892601,14976483,255,220),
(4001081009,3892602,14976477,80,150),
(4001080961,3892601,14975242,130,150),
(4001081061,3892601,14976484,160,170),
(4001081275,3892601,14976485,85,30),
(4001083555,3892602,14947558,70,80),
(4001083818,3892601,14976486,60,50)]
# workout_id, source week, source zero-index day, destination zero-index day
MOVES=[
(4001071997,17,2,5),(4001072083,17,5,6),(4001072135,17,5,6),(4001072163,17,6,2),
(4001074490,18,2,6),(4001074593,18,6,2),
(4001078777,20,2,6),(4001078902,20,6,2),
(4001081009,21,2,5),(4001081215,21,5,6),(4001081245,21,5,6),(4001081275,21,6,4),
(4001083555,22,2,6),(4001083818,22,6,4)]
TITLES={4001089818:"Attivazione | 1200 m facili - 30'",4001089870:"Attivazione | 1200 m facili - 30'"}
TOTALS={17:1020,18:980,19:1055,20:960,21:1200,22:920,23:600,24:210}
def must(x,msg):
 if not x:raise RuntimeError(msg)
def sig(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
def stable(x):return {k:v for k,v in x.items() if k!="lastModifiedDate"}
def datefor(week,d):return (date(2027,1,4)+timedelta(weeks=week-1,days=d)).isoformat()
def day(x):return str(x.get("workoutDay") or "")[:10]
async def snapshot(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_UNREADABLE")
 z=p.data
 must(z.get("planId")==PLAN and z.get("planPersonId")==PERSON and z.get("isPublic") is False and z.get("price") in (0,None) and z.get("workoutCount")==276,"WRONG_PLAN")
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
 must(not w.is_error and not n.is_error and isinstance(w.data,list) and len(w.data)==88 and isinstance(n.data,list),"BLOCK_SCOPE_DRIFT")
 must(len({v.get("workoutId") for v in w.data})==88,"DUPLICATE_WORKOUT_ID")
 return w.data,sig(n.data)
async def main():
 async with TPClient() as c:
  u=await c._get_user_data();must(u.get("personId")==OWNER,"WRONG_OWNER")
  base,notes=await snapshot(c);byid={v["workoutId"]:v for v in base}
  libs={}
  for lid in (3892601,3892602):
   r=await c.get(f"/exerciselibrary/v2/libraries/{lid}/items")
   must(not r.is_error and isinstance(r.data,list),"LIBRARY_READ_FAIL")
   libs[lid]={z.get("exerciseLibraryItemId"):z for z in r.data}
  patched={}
  for wid,lid,tid,old,new in TEMPLATES:
   src=byid.get(wid);temp=libs[lid].get(tid)
   must(src is not None and temp is not None and
        src.get("workoutTypeValueId")==(3 if lid==3892602 else 2) and
        abs(src["totalTimePlanned"]*60-old)<0.02 and
        abs(temp["totalTimePlanned"]*60-new)<0.02 and
        isinstance(temp.get("structure"),dict) and
        temp["itemName"].count("|")==1 and not any(c in temp["itemName"] for c in ("CHASING","W17","W21")),
        "TEMPLATE_PREFLIGHT_"+str(wid))
   v=dict(src)
   for k,key in (("title","itemName"),("description","description"),("totalTimePlanned","totalTimePlanned"),("distancePlanned","distancePlanned"),("structure","structure"),("workoutSubTypeId","workoutSubTypeId")):v[k]=temp.get(key)
   patched[wid]=v
  for wid,week,source,target in MOVES:
   v=byid.get(wid)
   must(v is not None and day(v)==datefor(week,source),"MOVE_PREFLIGHT_"+str(wid))
   v=patched.get(wid,dict(v))
   v["workoutDay"]=datefor(week,target)+str(byid[wid]["workoutDay"])[10:]
   patched[wid]=v
  for wid,title in TITLES.items():
   v=byid.get(wid)
   must(v is not None and "W24" in v.get("title","") and v.get("workoutTypeValueId")==1,"SWIM_TITLE_PREFLIGHT")
   patch=dict(v);patch["title"]=title;patched[wid]=patch
  must(len(patched)==20,"WRONG_PATCH_COUNT_"+str(len(patched)))
  must(not BACKUP.exists(),"BACKUP_EXISTS_CHECK_PROVIDER_NO_BLIND_RETRY")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":PLAN,"before":base,"notes_hash":notes,"patched_ids":sorted(patched)},ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"PREFLIGHT_PASS","count":88,"writes":len(patched),"scope":"W17-W24"}),flush=True)
  expected={wid:stable(v) for wid,v in byid.items()}
  for i,(wid,payload) in enumerate(patched.items()):
   before,ns=await snapshot(c);cur={x["workoutId"]:x for x in before}
   must(ns==notes and stable(cur[wid])==expected[wid],"WRITE_PREFLIGHT_DRIFT_"+str(wid))
   resp=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",json=payload,_retry_on_401=False)
   fresh,ns=await snapshot(c);fm={x["workoutId"]:x for x in fresh}
   must(not resp.is_error and ns==notes and stable(fm[wid])==stable(payload),"WRITE_NOT_VERIFIED_"+str(wid))
   expected[wid]=stable(payload)
   must(all(stable(fm[k])==v for k,v in expected.items()),"UNEXPECTED_WORKOUT_CHANGED")
   print(json.dumps({"stage":"VERIFIED","number":i+1,"id":wid}),flush=True)
  done,_=await snapshot(c)
  totals={w:round(sum((x.get("totalTimePlanned") or 0)*60 for x in done if datefor(w,0)<=day(x)<=datefor(w,6))) for w in range(17,25)}
  must(totals==TOTALS,"VOLUMES_WRONG_"+str(totals))
  peaks=[(w,round(x["totalTimePlanned"]*60),day(x)) for w in range(17,25) for x in done if datefor(w,0)<=day(x)<=datefor(w,6) and x.get("workoutTypeValueId")==3 and round(x["totalTimePlanned"]*60)>=150]
  must(len(peaks)==2 and sorted((w,m) for w,m,_ in peaks)==[(17,150),(21,150)],"TWO_PEAKS_FAILED_"+str(peaks))
  must(not any(datefor(19,6)==day(x) for x in done),"W19_SUNDAY_NOT_OFF")
  must(not any(("CHASING" in x.get("title","") or "W24" in x.get("title","")) for x in done),"TITLE_RULE_FAIL")
  print(json.dumps({"stage":"PASS_W17_W24","totals":totals,"run_peaks":peaks,"workout_ids_preserved":88,"notes_preserved":True,"plan_private":True,"no_athlete_write":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","reason":str(e)[:300]}),flush=True);raise
