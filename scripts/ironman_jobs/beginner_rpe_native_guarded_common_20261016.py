"""Guarded phased Beginner-only RPE Builder in-place update.
Native copy ids unchanged; strictly updates structure metric/targets/polyline.
No library, athlete or other plan call. Fail closed on any provider drift.
"""
import asyncio,json
from pathlib import Path
from tp_mcp.client import TPClient
from beginner_rpe_native_common_20261016 import (
 PLAN,OWNER,need,stable,digest,load_manifest,fetch_all,get_plan,patch
)
BASE=Path.home()/".trainingpeaks-mcp"
async def run_phase(week_from,week_to,expected_count):
 async with TPClient() as c:
  anchor=await get_plan(c)
  rows=load_manifest()
  before,notes=await fetch_all(c,anchor)
  target_ids=[wid for wid,row in sorted(rows.items(),key=lambda pair:(pair[1]["week"],pair[0]))
              if week_from<=row["week"]<=week_to]
  need(len(target_ids)==expected_count,"WRONG_BATCH_ID_COUNT")
  for wid,row in rows.items():
   cur=before.get(wid)
   need(cur is not None,"MISSING_MANIFEST_ID")
   metric=(cur.get("structure") or {}).get("primaryIntensityMetric")
   required="rpe" if row["week"]<week_from else "percentOfFtp"
   need(metric==required,"PHASE_ORDER_OR_SOURCE_DRIFT_"+str(wid))
  prepared={wid:patch(before[wid],rows[wid]) for wid in target_ids}
  need(len(prepared)==expected_count,"PREPARE_NOT_EXACT")
  expected={wid:stable(w) for wid,w in before.items()}
  backup=BASE/("beginner679801_rpe_w%02d_w%02d_20261016_before.json"%(week_from,week_to))
  need(not backup.exists(),"BACKUP_ALREADY_EXISTS_CHECK_PROVIDER_BEFORE_RETRY")
  BASE.mkdir(parents=True,exist_ok=True)
  backup.write_text(json.dumps({
    "plan":PLAN,"owner":OWNER,"batch":[week_from,week_to],
    "provider_original":before,"calendar_notes_hash":notes,
    "target_ids":target_ids,"scope":"NATIVE_RPE_METRIC_ONLY"
   },ensure_ascii=False,default=str,indent=2)+"\n")
  print(json.dumps({"stage":"BACKUP_AND_COMPILE_PASS","plan":PLAN,"weeks":[week_from,week_to],
       "target_count":expected_count,"cadence_preserved":sum(z[1]["cadence_fields"] for z in prepared.values()),
       "provider_writes_so_far":0}),flush=True)
  applied=0
  for wid in target_ids:
   fresh,nh=await fetch_all(c,anchor)
   need(nh==notes and set(fresh)==set(expected),"PREWRITE_CARD_OR_NOTES_DRIFT_"+str(wid))
   need(all(stable(w)==expected[w["workoutId"]] for w in fresh.values()),"PREWRITE_CONCURRENT_DRIFT_"+str(wid))
   q,_=prepared[wid]
   res=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",json=q,_retry_on_401=False)
   after,nh2=await fetch_all(c,anchor)
   need(nh2==notes and set(after)==set(expected),"POSTWRITE_NOTES_OR_COUNT_DRIFT_"+str(wid))
   need(not res.is_error,"PROVIDER_RETURNED_ERROR_AFTER_READBACK_"+str(wid))
   need(stable(after[wid])==stable(q),"POSTWRITE_NATIVE_BUILDER_DRIFT_"+str(wid))
   expected[wid]=stable(q)
   need(all(stable(w)==expected[w["workoutId"]] for w in after.values()),"UNRELATED_WORKOUT_CHANGED_"+str(wid))
   applied+=1
   if applied%5==0 or applied==expected_count:
    print(json.dumps({"stage":"READBACK_PASS_PROGRESS","weeks":[week_from,week_to],
        "written":applied,"planned":expected_count,"last_id":wid}),flush=True)
  final,finalnotes=await fetch_all(c,anchor)
  need(finalnotes==notes and all(stable(w)==expected[w["workoutId"]] for w in final.values()),"FINAL_RECONCILIATION_FAILED")
  counts={"ftp":0,"rpe":0}
  for wid,row in rows.items():
   metric=(final[wid].get("structure") or {}).get("primaryIntensityMetric")
   need(metric in ("percentOfFtp","rpe"),"UNEXPECTED_METRIC")
   counts["ftp" if metric=="percentOfFtp" else "rpe"]+=1
  need(counts["rpe"]==sum(1 for row in rows.values() if row["week"]<=week_to),"RPE_PROGRESS_COUNT_DRIFT")
  print(json.dumps({"stage":"BEGINNER_RPE_PHASE_VERIFIED","plan":PLAN,"weeks":[week_from,week_to],
    "written":applied,"rpe_converted_total":counts["rpe"],
    "ftp_to_convert_remaining":counts["ftp"],
    "provider_writes":applied,"other_workouts_unchanged":True,
    "calendar_notes_unchanged":True,"price_and_public_state_not_modified":True}),flush=True)
