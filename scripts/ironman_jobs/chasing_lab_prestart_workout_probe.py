"""Disposable canary: will moving a lab workout one day BEFORE plan start re-anchor plan?
Plan 684484 only; preserves two lab notes, restores workout.
"""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=684484
ID=3995256662
OLD="2027-07-06"
BEFORE_START="2027-07-04"
START_DATE="2027-07-05"
A="2027-07-02"
B="2027-07-15"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_lab_prestart_workout_canary.json"
def must(t,s):
 if not t:raise RuntimeError(s)
def checksum(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
def no_meta(x):return {k:v for k,v in x.items() if k!="lastModifiedDate" and k!="workoutDay"}
async def snap(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{A}/{B}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{A}/{B}")
 must(not p.is_error and not w.is_error and not n.is_error,"PROVIDER_READ_FAILED")
 must(isinstance(w.data,list) and isinstance(n.data,list) and len(n.data)==2,"CONTENT_DRIFT")
 return p.data,w.data,n.data
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  must(u.get("personId")==OWNER,"WRONG_OWNER")
  p,w,n=await snap(c)
  must(p.get("planId")==PLAN and p.get("isPublic") is False and
       str(p.get("startDate") or "")[:10]==START_DATE and len(w)==1 and
       w[0].get("workoutId")==ID and str(w[0].get("workoutDay") or "")[:10]==OLD,
       "LAB_INITIAL_DRIFT")
  must(not BACKUP.exists(),"PREVIOUS_PROBE_BACKUP_EXISTS")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":p,"workouts":w,"notes":n},ensure_ascii=False,indent=2)+"\n")
  changed=dict(w[0])
  changed["workoutDay"]=BEFORE_START+str(w[0]["workoutDay"])[10:]
  print(json.dumps({"stage":"PREFLIGHT","plan":PLAN,"old":OLD,"new":BEFORE_START}),flush=True)
  resp=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{ID}",json=changed,_retry_on_401=False)
  try:
   pm,wm,nm=await snap(c)
   print(json.dumps({"stage":"PRESTART_PROBE","put_error":resp.is_error,
      "before_start":START_DATE,"after_start":str(pm.get("startDate"))[:10],
      "workout_count":pm.get("workoutCount"),"workout_dates":[x.get("workoutDay") for x in wm],
      "notes_match":checksum(nm)==checksum(n)},ensure_ascii=False),flush=True)
  finally:
   pf,wf,nf=await snap(c)
   matches=[x for x in wf if x.get("workoutId")==ID]
   must(len(matches)==1,"WORKOUT_MISSING_MANUAL_RESTORE")
   if str(matches[0].get("workoutDay") or "")[:10]!=OLD:
    restore=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{ID}",json=w[0],_retry_on_401=False)
    must(not restore.is_error,"RESTORE_FAILED")
   pf,wf,nf=await snap(c)
   must(len(wf)==1 and wf[0].get("workoutId")==ID and
       str(wf[0].get("workoutDay") or "")[:10]==OLD and
       no_meta(wf[0])==no_meta(w[0]) and checksum(nf)==checksum(n),
       "RESTORATION_FAILED")
   print(json.dumps({"stage":"LAB_RESTORED","workout_dates_and_content":True,"notes_preserved":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP","reason":str(e)[:230],"no_blind_retry":True}),flush=True)
  raise
