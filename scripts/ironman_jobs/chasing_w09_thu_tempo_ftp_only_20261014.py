"""Correct only CHASING W09 Thursday bike steady native Builder RPE -> percentOfFtp.
No title, text, library, other workout, notes, athlete or structural workout changes.
"""
import asyncio,copy,json
from pathlib import Path
from datetime import date
from tp_mcp.client import TPClient
from tp_mcp.tools.library import _ensure_structure_preview

PLAN=685173;OWNER=2116886;PERSON=6682479
WID=4001048439
TECH_DATE="2027-03-04"
START="2027-03-01";END="2027-03-07"
TITLE="Steady | 130' 3x10' tempo controllato +15' facile"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w09_thu_tempo_ftp_only_20261014_backup.json"
TARGETS=(("warmUp",900,50,60),("active",600,80,85),("rest",900,55,65),
         ("active",1800,60,70),("coolDown",600,45,55))

def need(condition,message):
 if not condition:raise RuntimeError(message)
def stable(x):
 return {k:v for k,v in x.items() if k!="lastModifiedDate"}
def steps(s):
 return [step for grp in s.get("structure") or [] for step in grp.get("steps") or []]
async def read_week(c):
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
 need(not w.is_error and not n.is_error and isinstance(w.data,list) and isinstance(n.data,list),"PROVIDER_READ_FAIL")
 return w.data,n.data
async def main():
 async with TPClient() as c:
  user=await c._get_user_data()
  need(user.get("personId")==OWNER,"OWNER_DRIFT")
  plan=await c.get(f"/plans/v1/plans/{PLAN}")
  p=plan.data
  need(not plan.is_error and p.get("planId")==PLAN and p.get("planPersonId")==PERSON and
       p.get("isPublic") is False and p.get("workoutCount")==276 and "BOZZA" in (p.get("title") or ""),"PLAN_GUARD")
  before,notes=await read_week(c)
  need(len(before)==10,"W09_ENDURANCE_COUNT_DRIFT_"+str(len(before)))
  same={w["workoutId"]:w for w in before}
  need(WID in same,"W09_THU_ID_NOT_FOUND")
  w=same[WID]
  need(str(w.get("workoutDay"))[:10]==TECH_DATE and (date.fromisoformat(TECH_DATE)-date.fromisoformat("2027-01-04")).days==59,"WRONG_WEEK_DAY")
  need(w.get("workoutTypeValueId")==2 and w.get("title")==TITLE and
       abs(w.get("totalTimePlanned")*60-130)<0.001 and
       "RPE4" in (w.get("description") or ""),"SOURCE_WRONG")
  old=w.get("structure") or {}
  need(old.get("primaryIntensityMetric")=="rpe" and old.get("primaryLengthMetric")=="duration","SOURCE_NOT_RPE_RECONCILE")
  original=steps(old)
  need(len(original)==5 and len(old.get("structure") or [])==4,"SHAPE_WRONG")
  for i,(cl,sec,low,high) in enumerate(TARGETS):
   s=original[i]
   need(s.get("intensityClass")==cl and s.get("length")=={"value":sec,"unit":"second"} and
        len(s.get("targets") or [])==1,"STEP_NOT_MATCH_"+str(i))
  need((old["structure"][1].get("type")=="repetition") and
       old["structure"][1].get("length")=={"value":3,"unit":"repetition"},"THREE_REPS_MISSING")
  updated=copy.deepcopy(w)
  st=updated["structure"]
  for z,(_,__,lo,hi) in zip(steps(st),TARGETS):
   z["targets"][0]["minValue"]=lo
   z["targets"][0]["maxValue"]=hi
  st["primaryIntensityMetric"]="percentOfFtp"
  st["primaryIntensityTargetOrRange"]="range"
  st.pop("polyline",None)
  updated["structure"]=_ensure_structure_preview(st)
  need(len(updated["structure"].get("polyline") or [])>=10,"POLYLINE_ABSENT")
  need(all(updated[k]==w[k] for k in w if k!="structure"),"NON_STRUCTURE_CHANGED")
  ca=copy.deepcopy(old);cb=copy.deepcopy(updated["structure"])
  for x in (ca,cb):
   for k in ("primaryIntensityMetric","primaryIntensityTargetOrRange","polyline"):x.pop(k,None)
   for step in steps(x):step.pop("targets",None)
  need(ca==cb,"BLOCKS_OR_TIMES_CHANGED")
  need(not BACKUP.exists(),"EXISTING_BACKUP_RECONCILE")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":PLAN,"workout":w,"week_before":before,"notes_before":notes},ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"PREFLIGHT_PASS","week":9,"day":"THU","workout_id":WID,"metric_from":"rpe","metric_to":"percentOfFtp","tempo":"80-85","other_fields":"unchanged"}),flush=True)
  res=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{WID}",json=updated,_retry_on_401=False)
  after,after_notes=await read_week(c)
  by={w["workoutId"]:w for w in after}
  need(not res.is_error and before and notes==after_notes,"PUT_OR_NOTES_NOT_PASS")
  need(set(by)==set(same),"W09_IDS_DRIFT")
  need(stable(by[WID])==stable(updated),"TARGET_DIFF_NOT_EXACT")
  need(all(stable(by[id])==stable(v) for id,v in same.items() if id!=WID),"OTHER_W09_CHANGED")
  need(by[WID]["structure"]["primaryIntensityMetric"]=="percentOfFtp","METRIC_WRONG")
  need([(z["targets"][0]["minValue"],z["targets"][0]["maxValue"]) for z in steps(by[WID]["structure"])] ==
       [(lo,hi) for _,__,lo,hi in TARGETS],"PERCENTAGES_WRONG")
  print(json.dumps({"stage":"PASS_VERIFIED_W09_THU_FTP_ONLY","workout_id":WID,"w09_other_workouts_unchanged":len(before)-1,"notes_unchanged":True,"titles_descriptions_unchanged":True,"library_athlete_writes":0}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","reason":str(e)[:450]}),flush=True)
  raise
