"""Fail-closed first-workout validation, grounded in canonical IRONMAN Google Drive docs.

Source-of-truth citations:
01_MASTER_COACHING_CONTEXT: 'Principio intensità — zona = territorio, workout = sottofascia'
02_DECISION_LOG: Intermediate double reading %FTP+RPE / % Run Threshold Pace+RPE
05_WORKOUT_TRAINING_PLAN_SYSTEM: naming; native Builder; intensity by purpose.

The profiles are STRICT, LIMITED examples, not a blanket mapping for Chasing.
Race pace (bike/run), tests, threshold outliers, no-meter, and other profiles must
have their OWN canonical specification and separate golden prototype.
"""
import math,re
from typing import Any

POLICY_VERSION="IRONMAN_GOLDEN_FIRST_2026_10_13"
# Ranges below reproduce current canonical operational sub-ranges, NOT TP numbered zones.
ROLE_BOUNDS={
 "BI_WARMUP":(40,65), # a ramp may contain recovery/easy; not an FTP zone
 "BI_ENDURANCE":(60,70),
 "BI_EASY":(55,65),
 "BI_COOLDOWN":(0,55), # upper value 55 is boundary convention
 "RU_WARMUP":(70,82),
 "RU_EASY":(78,84),
 "RU_COOLDOWN":(70,78),
}
PROFILE={
 "bike_endurance":{"sport":2,"metric":"percentOfFtp","required_roles":{"BI_ENDURANCE"}},
 "run_easy":{"sport":3,"metric":"percentOfThresholdPace","required_roles":{"RU_EASY"}},
}
BANNED=re.compile(r"(?i)\b(?:CHASING|IRONMAN\s+INTERMEDIATE|W(?:0?[1-9]|1[0-9]|2[0-4])|WEEK\s*\d+|SETTIMANA\s*\d+)\b")
def fail(code):raise ValueError("GOLDEN_FIRST_FAIL:"+code)
def validate(workout:dict[str,Any], *,profile:str, roles:list[str],
             expected_minutes:float, exact_titles:bool=True)->dict:
 if profile not in PROFILE:fail("CANONICAL_PROFILE_NOT_APPROVED")
 spec=PROFILE[profile]
 sport=workout.get("workoutTypeValueId",workout.get("sport_family_id"))
 if sport!=spec["sport"]:fail("SPORT_MISMATCH")
 title=workout.get("title",workout.get("itemName",""))
 if not isinstance(title,str) or title.count("|")!=1 or BANNED.search(title):fail("NOT_REUSABLE_TITLE")
 family,detail=(p.strip() for p in title.split("|"))
 if not family or not detail:fail("EMPTY_TITLE_FIELD")
 # IM pace has no approved universal mapping; reject it under easy/endurance profiles.
 if re.search(r"(?i)\b(?:IM\s*(?:Pace|Bike|Run)|ritmo\s+gara|race\s+pace)\b",title):
  fail("RACE_SPECIFIC_POLICY_REQUIRED")
 description=workout.get("description") or ""
 if not isinstance(description,str) or "RPE" not in description:fail("NO_RPE_SECOND_READING")
 if spec["sport"]==2 and not re.search(r"(?:%\s*(?:FTP|ftp)|percento\s+FTP)",description):
  fail("BIKE_FTP_SECOND_READING_MISSING")
 if spec["sport"]==3 and not re.search(r"(?i)(?:%\s*(?:della\s+)?(?:velocit[aà]|soglia)|velocit[aà]\s+di\s+soglia)",description):
  fail("RUN_THRESHOLD_SECOND_READING_MISSING")
 h=workout.get("totalTimePlanned")
 if not isinstance(h,(int,float)) or not math.isfinite(h) or abs(h*60-expected_minutes)>.05:
  fail("PLANNED_DURATION_MISMATCH")
 structure=workout.get("structure")
 if not isinstance(structure,dict):fail("NO_NATIVE_BUILDER")
 if structure.get("primaryLengthMetric")!="duration":fail("WRONG_LENGTH_METRIC")
 if structure.get("primaryIntensityMetric")!=spec["metric"]:fail("WRONG_QUANTITATIVE_METRIC")
 if structure.get("primaryIntensityTargetOrRange")!="range":fail("MISSING_TARGET_RANGE_MODE")
 graphic=structure.get("polyline")
 if not isinstance(graphic,list) or len(graphic)<6:fail("POLYLINE_MISSING")
 groups=structure.get("structure")
 if not isinstance(groups,list) or not groups:fail("STEPS_MISSING")
 steps=[];cursor=0.0
 for g in groups:
  if g.get("type") not in ("step","repetition"):fail("BAD_GROUP_TYPE")
  reps=g.get("length",{}).get("value")
  if not isinstance(reps,(int,float)) or reps<1 or reps!=int(reps):fail("BAD_REPETITIONS")
  if not isinstance(g.get("steps"),list) or not g["steps"]:fail("EMPTY_GROUP")
  seconds=0
  for step in g["steps"]:
   ln=step.get("length",{})
   sec=ln.get("value")
   if ln.get("unit")!="second" or not isinstance(sec,(int,float)) or sec<=0:
    fail("BAD_STEP_DURATION")
   targets=step.get("targets")
   if not isinstance(targets,list) or len(targets)!=1:fail("TARGET_MISSING_OR_MULTI")
   target=targets[0]
   mn,mx=target.get("minValue"),target.get("maxValue")
   if not isinstance(mn,(int,float)) or not isinstance(mx,(int,float)) or not math.isfinite(mn) or not math.isfinite(mx) or mn>mx:
    fail("BAD_TARGET_RANGE")
   if step.get("openDuration") is True:fail("OPEN_DURATION_UNAPPROVED")
   seconds+=sec
   steps.append((step,mn,mx))
  if g.get("begin") is not None and abs(g["begin"]-cursor)>1:fail("GROUP_BEGIN_DRIFT")
  cursor+=seconds*reps
  if g.get("end") is not None and abs(g["end"]-cursor)>1:fail("GROUP_END_DRIFT")
 if abs(cursor-expected_minutes*60)>2:fail("BUILDER_DURATION_MISMATCH")
 if len(roles)!=len(steps):fail("UNMAPPED_STEP_ROLE")
 if not spec["required_roles"].issubset(set(roles)):fail("MISSING_FUNCTIONAL_CORE")
 for (step,mn,mx),role in zip(steps,roles):
  if role not in ROLE_BOUNDS:fail("UNKNOWN_CANONICAL_ROLE")
  if not role.startswith("BI_" if spec["sport"]==2 else "RU_"):fail("CROSS_SPORT_ROLE")
  low,high=ROLE_BOUNDS[role]
  if mn<low-0.0001 or mx>high+0.0001:fail("TARGET_OUTSIDE_APPROVED_SUBRANGE:"+role)
  if role.endswith("ENDURANCE") or role.endswith("EASY"):
   if step.get("intensityClass")!="active":fail("FUNCTIONAL_SEGMENT_CLASS_MISMATCH")
  if role.endswith("WARMUP") and step.get("intensityClass")!="warmUp":fail("WARMUP_CLASS_MISMATCH")
  if role.endswith("COOLDOWN") and step.get("intensityClass")!="coolDown":fail("COOLDOWN_CLASS_MISMATCH")
 return {"gate":POLICY_VERSION,"status":"PASS","profile":profile,"title":title,
    "metric":spec["metric"],"duration_minutes":expected_minutes,"mapped_steps":len(steps)}
