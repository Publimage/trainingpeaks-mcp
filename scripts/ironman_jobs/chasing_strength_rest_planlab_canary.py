"""Sacrificial test of updating an existing native Strength workout IN PLACE in LAB
Training Plan 684543. Verify ID/count/notes then restore original. Never Chasing.
"""
import asyncio,copy,json,httpx
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
OWNER=2116886;PLAN=684543;PERSON=6678164;ID="33903234"
TITLE="[MCP TEST] TP Native Strength Plan Route 2026-10-09"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_rest_planlab_canary_backup.json"
def must(x,s):
 if not x:raise RuntimeError(s)
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  must(isinstance(u,dict) and u.get("personId")==OWNER and not p.is_error,"OWNER_OR_PLAN")
  d=p.data
  must(d.get("planId")==PLAN and d.get("planPersonId")==PERSON and d.get("title")==TITLE
       and d.get("workoutCount")==6 and d.get("isPublic") is False,"LAB_SCOPE_CHANGED")
  _,token,err=await _access(c);must(not err and token,"TOKEN")
  headers=_headers(token)
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   async def read():
    r=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/{ID}",headers=headers)
    must(r.status_code==200,"WORKOUT_READ_FAILED")
    w=r.json().get("data") or {}
    must(str(w.get("id"))==ID and w.get("calendarId")==PERSON and
         w.get("workoutType")=="StructuredStrength","NOT_SACRIFICIAL_WORKOUT")
    return w
   original=await read()
   patched=copy.deepcopy(original)
   pres=(patched.get("blocks") or [])[0].get("prescriptions") or []
   must(len(pres)>0,"LAB_HAS_NO_PRESCRIPTIONS")
   existing=pres[0].get("coachNotes")
   marker="\n[LAB EXISTING PLAN REST PATCH TEST: RESTORE AFTERWARD]"
   must(marker not in str(existing or ""),"LAB_PREVIOUS_MARKER")
   pres[0]["coachNotes"]=(existing or "")+marker
   must(not BACKUP.exists(),"BACKUP_ALREADY_EXISTS_NO_BLIND_RETRY")
   BACKUP.parent.mkdir(parents=True,exist_ok=True)
   BACKUP.write_text(json.dumps({"plan":PLAN,"workout":original},ensure_ascii=False,indent=2)+"\n")
   print(json.dumps({"stage":"PREFLIGHT","plan":PLAN,"workout_id":ID,
        "target_existing":True,"notes_only":True}),flush=True)
   res=await h.post(STRENGTH_API_BASE+f"/rx/activity/v1/plans/{PLAN}/workouts/save",
                    headers=headers,json=patched)
   try:
    now=await read()
    cur=now["blocks"][0]["prescriptions"][0].get("coachNotes")
    pp=await c.get(f"/plans/v1/plans/{PLAN}")
    must(res.status_code==200 and cur==pres[0]["coachNotes"] and
         not pp.is_error and pp.data.get("workoutCount")==6,"EXISTING_WORKOUT_UPDATE_NOT_VERIFIED")
    must(now.get("prescribedDurationInSeconds")==original.get("prescribedDurationInSeconds"),
         "DURATION_DRIFT")
    print(json.dumps({"stage":"LAB_INPLACE_REST_NOTES_PASS","unchanged_count":6,
       "unchanged_id":True,"duration_unchanged":True}),flush=True)
   finally:
    current=await read()
    if current["blocks"][0]["prescriptions"][0].get("coachNotes")!=existing:
     rr=await h.post(STRENGTH_API_BASE+f"/rx/activity/v1/plans/{PLAN}/workouts/save",
                       headers=headers,json=original)
     must(rr.status_code==200,"LAB_RESTORE_HTTP_FAILED")
    done=await read()
    final=await c.get(f"/plans/v1/plans/{PLAN}")
    must(done["blocks"][0]["prescriptions"][0].get("coachNotes")==existing and
         not final.is_error and final.data.get("workoutCount")==6,"LAB_RESTORE_VERIFICATION_FAILED")
    print(json.dumps({"stage":"LAB_RESTORED","same_id":True,"same_count":6}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_NO_RETRY","reason":str(e)[:230]}),flush=True)
  raise
