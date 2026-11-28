"""Strict, auditable bike/run endurance-only target mapping, no universal race-pace assumption.
Grounded in Intermediate canonical worksheet / CANONICAL_WORKOUTS examples:
Bike W04 easy: warm 50-60, easy 55-65, cool 45-55 %FTP.
Bike W01 long: warm 50-60, endurance 60-65, aero 65-70, cool 45-55 %FTP.
Run W02 easy: warm 76-82, easy 78-84, cool 70-78 %threshold speed.
01_MASTER_COACHING_CONTEXT and 05_WORKOUT_TRAINING_PLAN_SYSTEM concur.
All dates in adapter are transport only. Plan identity is relative week/day.
"""
import re,json
from datetime import date
from tp_mcp.tools.library import _ensure_structure_preview
PLAN_START_TRANSPORT=date(2027,1,4)
RACE=re.compile(r"(?i)(?:\bIM\s*(?:Bike|Run)?\s*Pace\b|\bIronman\s*(?:Bike|Run)?\s*Pace\b|\brace execution\b|\britmo gara\b|\bpasso im\b|\britmo im\b|\bdiagnostic[oa]\b|\bdiagnostico\b)")
QUALITY=re.compile(r"(?i)(?:\b(?:soglia|threshold|vo2|steady|tempo controllato|tempo alto|intervalli|over-under|fartlek|ripetute|qualit[aà])\b)")
TEST=re.compile(r"(?i)^(?:Test|Retest)\s*\|")
WEEKNAME=re.compile(r"(?i)\b(?:W(?:0?[1-9]|1[0-9]|2[0-4])|SETTIMANA|CHASING)\b")
def relative(w):
 d=date.fromisoformat(str(w.get("workoutDay") or "")[:10]);delta=(d-PLAN_START_TRANSPORT).days
 if delta<0 or delta>=168:raise ValueError("OUTSIDE_RELATIVE_PLAN_SCOPE")
 return (delta//7+1,delta%7)
def classify(w):
 sport=w.get("workoutTypeValueId")
 if sport not in (2,3):return "NOT_BIKE_RUN"
 structure=w.get("structure") or {}
 if structure.get("primaryIntensityMetric")!="rpe":return "ALREADY_QUANTITATIVE"
 wk,wd=relative(w)
 title=w.get("title") or ""
 if wk==1:return "INITIAL_TEST_WEEK_RPE_EXCEPTION"
 if TEST.search(title):return "TEST_RPE_EXCEPTION"
 if wk==24 and sport==3 and title.startswith("Attivazione"):return "RACE_WEEK_SHORT_RPE_EXCEPTION"
 words=title+" "+ " ".join(z.get("name","") for g in structure.get("structure") or [] for z in g.get("steps") or [])
 if RACE.search(words):return "RACE_PACE_REQUIRES_OWN_APPROVED_PROFILE"
 if QUALITY.search(words):return "QUALITY_REQUIRES_OWN_APPROVED_PROFILE"
 if not (structure.get("primaryLengthMetric")=="duration" and structure.get("structure")):return "INVALID_OR_MISSING_BUILDER"
 return "BI_ENDURANCE" if sport==2 else "RU_ENDURANCE"
def target_for(w,step):
 sport=w["workoutTypeValueId"];s=(step.get("name") or "").lower();cl=step.get("intensityClass")
 title=(w.get("title") or "").lower()
 if sport==2:
  if cl=="warmUp":return (50,60,"BI_WARMUP_INTERMEDIATE_EXAMPLE")
  if cl=="coolDown":return (45,55,"BI_COOLDOWN_INTERMEDIATE_EXAMPLE")
  if cl=="rest":return (55,65,"BI_EASY_REST")
  if cl!="active":raise ValueError("UNKNOWN_BIKE_STEP_CLASS")
  if re.search(r"\baero\b",s):return (65,72,"BI_AERO_ENDURANCE")
  if "recupero" in title and "endurance" not in s and "fondo" not in s:return (45,54,"BI_RECOVERY")
  if any(p in s for p in ("endurance","lungo","fondo","lt1","aerobico")):return (60,65,"BI_ENDURANCE_INTERMEDIATE_EXAMPLE")
  if any(p in s for p in ("facile","agile","circolazione")):return (55,65,"BI_EASY_INTERMEDIATE_EXAMPLE")
  raise ValueError("UNKNOWN_BIKE_ACTIVE_STEP:"+s)
 if sport==3:
  is_rec="recupero" in title
  if cl=="warmUp":return (70,78,"RU_RECOVERY") if is_rec else (76,82,"RU_WARMUP_INTERMEDIATE_EXAMPLE")
  if cl=="coolDown":return (70,78,"RU_COOLDOWN_INTERMEDIATE_EXAMPLE")
  if cl=="rest":return (70,78,"RU_RECOVERY")
  if cl!="active":raise ValueError("UNKNOWN_RUN_CLASS")
  if is_rec or "recupero" in s:return (70,78,"RU_RECOVERY")
  if "lungo" in title or "lungo" in s:return (80,86,"RU_LONG")
  if any(p in s for p in ("fondo","facile","aerob","conversaz","sciolto","lento","easy")):
   return (78,84,"RU_EASY_INTERMEDIATE_EXAMPLE")
  raise ValueError("UNKNOWN_RUN_ACTIVE_STEP:"+s)
 raise ValueError("SPORT")
def recipe(w):
 cl=classify(w)
 if cl not in ("BI_ENDURANCE","RU_ENDURANCE"):return None,cl
 import copy
 v=copy.deepcopy(w);s=v["structure"]
 meta=[];seen=0
 for g in s["structure"]:
  for step in g.get("steps") or []:
   lo,hi,role=target_for(w,step)
   if not step.get("targets"):raise ValueError("SOURCE_TARGETS_MISSING")
   step["targets"]=[{"minValue":lo,"maxValue":hi}]
   meta.append((step["name"],lo,hi,role));seen+=1
 if seen==0:raise ValueError("NO_STEPS")
 s["primaryIntensityMetric"]="percentOfFtp" if w["workoutTypeValueId"]==2 else "percentOfThresholdPace"
 s["primaryIntensityTargetOrRange"]="range"
 s.pop("polyline",None)
 v["structure"]=_ensure_structure_preview(s)
 if not v["structure"].get("polyline"):raise ValueError("POLYLINE_NOT_GENERATED")
 olddesc=w.get("description") or ""
 if "RPE" not in olddesc:raise ValueError("RPE_SECOND_READING_MISSING")
 spec="BI %FTP" if w["workoutTypeValueId"]==2 else "RU %velocita soglia"
 lines="; ".join(f"{name}: {lo}-{hi}%"+(" FTP" if w["workoutTypeValueId"]==2 else " velocita soglia") for name,lo,hi,role in meta)
 prefix=("TARGET NEL BUILDER (%FTP)\n"+lines+"\nFTP personale aggiornata dopo test valido. RPE nella prescrizione resta seconda lettura, con controllo del rapporto fra output e costo interno.\n\n") if w["workoutTypeValueId"]==2 else ("TARGET NEL BUILDER (% VELOCITA DI SOGLIA)\n"+lines+"\nRun Threshold Pace individuale aggiornata dopo 5 km valido. RPE resta seconda lettura per caldo, dislivello e tolleranza muscolare.\n\n")
 v["description"]=prefix+olddesc
 v["title"]=w["title"]+(" - %FTP" if w["workoutTypeValueId"]==2 else " - %soglia")
 if v["title"].count("|")!=1 or WEEKNAME.search(v["title"]):raise ValueError("TITLE_NOT_NEUTRAL")
 if v.get("totalTimePlanned")!=w.get("totalTimePlanned"):raise ValueError("DURATION_DRIFT")
 if v.get("workoutDay")!=w.get("workoutDay"):raise ValueError("RELATIVE_DAY_DRIFT")
 if v["structure"]["structure"][-1]["end"]!=w["structure"]["structure"][-1]["end"]:raise ValueError("BLOCK_SECONDS_CHANGED")
 return {"id":w["workoutId"],"week":relative(w)[0],"day":relative(w)[1],
         "sport":w["workoutTypeValueId"],"old_title":w["title"],"new_title":v["title"],
         "before":w,"after":v,"mapping":meta},cl
