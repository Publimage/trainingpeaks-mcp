"""Resume once after verified golden W10. Eight exact CHASING plan bike copies, no further canary."""
import asyncio,copy,json
from pathlib import Path
from tp_mcp.client import TPClient
from chasing_paceplus_nine_20261014 import (
 P,OWNER,PERSON,SETS,BACKUP,need,stable,sha,patched,readweek
)
FIRST=4001050288
IDS=tuple(wid for wid in SETS if wid!=FIRST)
assert len(IDS)==8 and len(set(IDS))==8
async def main():
 need(BACKUP.exists(),"GOLDEN_BACKUP_NOT_FOUND")
 b=json.loads(BACKUP.read_text())
 need(b.get("plan")==P and set(map(int,b.get("original") or {}))==set(SETS),"BACKUP_DRIFT")
 originals={int(k):v for k,v in b["original"].items()}
 desired={i:patched(originals[i],i) for i in SETS}
 async with TPClient() as c:
  me=await c._get_user_data()
  need(me.get("personId")==OWNER,"OWNER")
  response=await c.get(f"/plans/v1/plans/{P}")
  info=response.data or {}
  need(not response.is_error and info.get("planId")==P and info.get("planPersonId")==PERSON
       and info.get("isPublic") is False and info.get("workoutCount")==276
       and "BOZZA" in (info.get("title") or ""),"PLAN_SCOPE")
  weeks=sorted({SETS[i][0] for i in SETS})
  beforeweeks={}
  for wk in weeks:
   rows,notes=await readweek(c,wk)
   need(sha(notes)==b["notehash"][str(wk)],"CALENDAR_NOTES_DRIFT")
   beforeweeks[wk]={x["workoutId"]:stable(x) for x in rows}
  first=beforeweeks[SETS[FIRST][0]].get(FIRST)
  need(first==stable(desired[FIRST]),"W10_GOLDEN_NOT_VERIFIED")
  for wid in IDS:
   now=beforeweeks[SETS[wid][0]].get(wid)
   need(now==stable(originals[wid]),"UNEXPECTED_LIVE_DRIFT_"+str(wid))
  print(json.dumps({"stage":"RESUME_PREFLIGHT_PASS","golden_w10":"verified",
                    "remaining":list(IDS),"untouched_neighbors":True}),flush=True)
  for wid in IDS:
   wk=SETS[wid][0]
   rows,notes=await readweek(c,wk)
   before={x["workoutId"]:stable(x) for x in rows}
   need(before.get(wid)==stable(originals[wid]),"PREWRITE_DRIFT_"+str(wid))
   need(sha(notes)==b["notehash"][str(wk)],"NOTES_DRIFT_"+str(wid))
   res=await c._request("PUT",f"/plans/v1/plans/{P}/workouts/{wid}",json=desired[wid],_retry_on_401=False)
   rows2,notes2=await readweek(c,wk)
   after={x["workoutId"]:stable(x) for x in rows2}
   need(not res.is_error and after.get(wid)==stable(desired[wid]),"PUT_NOT_VERIFIED_"+str(wid))
   need(sha(notes2)==b["notehash"][str(wk)],"NOTES_CHANGED_"+str(wid))
   need(set(before)==set(after),"WORKOUT_SET_CHANGED_"+str(wid))
   need(all(after[k]==(stable(desired[wid]) if k==wid else v)
            for k,v in before.items()),"NEIGHBOR_DRIFT_"+str(wid))
   print(json.dumps({"stage":"VERIFIED_ONE","id":wid,"week":wk,
      "fixed_total_min":SETS[wid][7]+SETS[wid][2]*(SETS[wid][3]+SETS[wid][6])+SETS[wid][8]+SETS[wid][9]}),flush=True)
  for wk in weeks:
   rows,notes=await readweek(c,wk)
   now={x["workoutId"]:stable(x) for x in rows}
   need(sha(notes)==b["notehash"][str(wk)],"FINAL_NOTES_DRIFT")
   for wid in SETS:
    if SETS[wid][0]==wk:need(now.get(wid)==stable(desired[wid]),"FINAL_TARGET_DRIFT_"+str(wid))
   need(all(now.get(k)==v for k,v in beforeweeks[wk].items() if k not in SETS),
        "FINAL_NEIGHBOR_DRIFT_"+str(wk))
  print(json.dumps({"stage":"NINE_PACEPLUS_VERIFIED","count":len(SETS),"new_writes":len(IDS),
                    "golden_included":True,"scope":"trainingpeaks:plan:685173"}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"SAFE_STOP","reason":str(e)[:450]}),flush=True)
  raise
