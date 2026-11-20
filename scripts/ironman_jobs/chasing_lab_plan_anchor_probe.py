"""Disposable Training Plan startDate change+restore probe (plan 684484 only).
Reports whether header anchor moves native workout/note dates; never Chasing.
"""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=684484
TITLE="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
OLD="2027-07-05"
NEW="2027-07-04"
A="2027-07-02"
B="2027-07-15"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_plan_anchor_lab_canary_backup.json"

def must(v,s):
 if not v:raise RuntimeError(s)
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def stable(v):return {k:x for k,x in v.items() if k not in ("lastModifiedDate","lastUpdatedDate","modifiedDate")}
async def snap(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_READ_FAILED")
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{A}/{B}")
 must(not w.is_error and isinstance(w.data,list) and len(w.data)==1,"WORKOUT_READ_FAILED")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{A}/{B}")
 must(not n.is_error and isinstance(n.data,list) and len(n.data)==2,"NOTES_READ_FAILED")
 return p.data,w.data,n.data
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  plan,workouts,notes=await snap(c)
  must(plan.get("planId")==PLAN and plan.get("title")==TITLE and
       plan.get("isPublic") is False and plan.get("workoutCount")==1 and
       str(plan.get("startDate") or "")[:10]==OLD,"LAB_CHANGED")
  must(not BACKUP.exists(),"BACKUP_EXISTS_NO_RETRY")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":plan,"workouts":workouts,"notes":notes},ensure_ascii=False,indent=2)+"\n")
  edited=dict(plan)
  edited["startDate"]=NEW+str(plan["startDate"])[10:]
  print(json.dumps({"stage":"PREFLIGHT","plan":PLAN,"old":OLD,"new":NEW}),flush=True)
  result=await c._request("PUT",f"/plans/v1/plans/{PLAN}",json=edited,_retry_on_401=False)
  try:
   p2,w2,n2=await snap(c)
   print(json.dumps({"stage":"ANCHOR_PROBE","write_error":result.is_error,
    "reported_start":str(p2.get("startDate"))[:10],
    "workout_days_before":[x.get("workoutDay") for x in workouts],
    "workout_days_after":[x.get("workoutDay") for x in w2],
    "note_dates_before":[x.get("calendarNoteDate",x.get("noteDate")) for x in notes],
    "note_dates_after":[x.get("calendarNoteDate",x.get("noteDate")) for x in n2],
    "notes_exactly_preserved":digest(notes)==digest(n2)},ensure_ascii=False),flush=True)
  finally:
   live,_,_=await snap(c)
   if str(live.get("startDate") or "")[:10]!=OLD:
    restore=await c._request("PUT",f"/plans/v1/plans/{PLAN}",json=plan,_retry_on_401=False)
    must(not restore.is_error,"ANCHOR_RESTORE_REJECTED_MANUAL_RECOVERY")
   pf,wf,nf=await snap(c)
   must(str(pf.get("startDate") or "")[:10]==OLD and digest(notes)==digest(nf)
        and [x.get("workoutDay") for x in workouts]==[x.get("workoutDay") for x in wf],
        "LAB_RESTORATION_MISMATCH")
   print(json.dumps({"stage":"RESTORED","plan":PLAN,"notes_preserved":True,"workout_dates_preserved":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP","reason":str(e)[:230],"no_blind_retry":True}),flush=True)
  raise
