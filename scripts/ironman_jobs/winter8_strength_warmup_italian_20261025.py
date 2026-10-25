"""WINTER strength: in-place warm-up and Italian athlete-facing labels, no clones.

Touches exactly 16 native library templates and their 16 private plan instances.
Keeps all strength-work sets, exercise native IDs, recoveries, dose, duration,
calendar slots, plan privacy, library identities. Provider GET after each SAVE.
"""
from __future__ import annotations
import asyncio, copy, json, uuid
from pathlib import Path
import httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE,_catalogue,_build_prescription,_recount

ROOT=Path(__file__).resolve().parents[2]
LIB_FILE=ROOT/"data/ironman_strength_library_manifest.json"
PLAN_FILE=ROOT/"data/ironman_native_strength_plan_assembly.json"
LIB=3891875;OWNER=2116886;PLAN=689369;PERSON=6709024
LIB_NAME="ALBERTO FAZI ENDURANCE | Forza | IT"
PLAN_NAME="ALBERTO FAZI ENDURANCE | WINTER FOUNDATION | 8 settimane | Italiano"
BASE="/rx/activity/v1"
MARK="RISCALDAMENTO DINAMICO IN QUATTRO ESERCIZI"
RENAMES={
 "FORZA | Unilaterale e upper body 45 min":"FORZA | Unilaterale e parte superiore 45 min",
 "FORZA | Step-up mono e upper body 55 min":"FORZA | Salita su rialzo e parte superiore 55 min",
 "FORZA | Step-up mono di richiamo 55 min":"FORZA | Salita su rialzo di richiamo 55 min",
 "FORZA | Hip thrust e richiamo 55 min":"FORZA | Spinta d'anca e richiamo 55 min",
}
IT={
 "Goblet squat":"Squat con manubrio",
 "Back squat con bilanciere":"Squat con bilanciere",
 "Romanian deadlift":"Stacco rumeno",
 "Stacco con kettlebell":"Stacco con kettlebell",
 "Stacco da terra":"Stacco da terra",
 "Panca manubri":"Distensioni su panca con manubri",
 "Panca piana":"Distensioni su panca con bilanciere",
 "Lat-machine":"Trazioni alla lat machine",
 "Calf raise":"Sollevamenti sui polpacci",
 "Bird dog":"Estensioni alternate in quadrupedia",
 "Glute bridge":"Ponte per i glutei",
 "Hip thrust con bilanciere":"Spinta d'anca con bilanciere",
 "Weighted Step Up":"Salita su rialzo con carico",
 "Step-up controllato":"Salita su rialzo controllata",
 "Split squat":"Affondo statico",
 "Push-up":"Piegamenti sulle braccia",
 "Side plank":"Plank laterale",
 "Plank":"Plank",
}
WARM_EX=[
 ("5184",{"Duration":45},"Mobilita delle caviglie, movimenti lenti 20-25 s per lato."),
 ("5305",{"RepsPerSide":6},"Circonduzioni delle anche controllate, 6 per lato."),
 ("475",{"Reps":8},"Mobilita della colonna in quadrupedia, 8 ripetizioni fluide."),
 ("7",{"Reps":12},"Aperture delle braccia con elastico leggero, scapole controllate; nessuna fatica."),
]
BACKUP=Path.home()/".trainingpeaks-mcp"/"winter8_strength_italian_warmup4_backup_20261025.json"

def log(**v):print(json.dumps(v,ensure_ascii=False),flush=True)
def must(ok,error):
 if not ok:raise ValueError(error)
def source_rows():
 a=json.loads(LIB_FILE.read_text(encoding="utf-8"))
 b=json.loads(PLAN_FILE.read_text(encoding="utf-8"))
 must(a.get("native_status")=="PUBLISHED_NATIVE_LIBRARY_PROVIDER_VERIFIED"
      and b.get("provider_plan_id")==PLAN and b.get("provider_plan_person_id")==PERSON,"MANIFEST_SCOPE")
 rows=a.get("items") or [];plans=b.get("workouts") or []
 must(len(rows)==len(plans)==16 and len({x.get("provider_item_id") for x in rows})==16,"MANIFEST_COUNT")
 must(sum(int(x.get("planned_duration_seconds",0)) for x in rows)==50700,"MANIFEST_DURATION")
 for i,(x,p) in enumerate(zip(rows,plans)):
  must(x.get("canonical_uid")==p.get("source_uid") and
       str(x.get("provider_item_id"))==str(p.get("native_item_id")) and
       x.get("title")==p.get("title") and
       str(p.get("plan_native_workout_id")) not in ("None",""),"MAPPING_"+str(i))
  must(x["title"].count("|")==1 and "WINTER" not in x["title"],"UNSAFE_TITLE")
 return rows,plans

def new_title(title):return RENAMES.get(title,title)
def warm_minutes(item):
 return int(item["warmup_minutes"])

def warmup_block(item,previous):
 min_=warm_minutes(item)
 main=(f"{MARK}. "
       f"Durata totale indicativa {min_} minuti, compresi passaggi tra gli esercizi. "
       "Eseguire in ordine: caviglie, anche, mobilita della colonna, "
       "aperture scapolari con elastico. Intensita molto facile, nessuna serie a cedimento. ")
 if min_>=10:
  main+=("Circa 7-8 minuti di mobilita e attivazione, poi "
         "2-4 minuti di avvicinamento progressivo al carico nel primo fondamentale.")
 else:
  main+=("Se e previsto un esercizio con carico, aggiungere nel tempo totale "
         "una breve serie leggera di avvicinamento, senza affaticarsi.")
 cat=_catalogue()
 ps=[_build_prescription({"id":id,"sets":[sets],
                          "notes":text+" Nessun recupero obbligatorio; 10-20 s per cambiare esercizio."},cat)
     for id,sets,text in WARM_EX]
 return {"id":previous.get("id") or str(uuid.uuid4()),"blockType":"WarmUp",
         "title":"Mobilita e attivazione generale","coachNotes":main,"prescriptions":ps}

def translate(text):
 t=text or ""
 for old,new in [
  ("FOOT CORE","ESERCIZI PER IL PIEDE"),
  ("Foot core","Esercizi per il piede"),
  ("Short Foot","attivazione dell'arco plantare (short foot)"),
  ("Toe Yoga","mobilita delle dita (toe yoga)"),
  ("Toe Tap","tocchi controllati delle dita (Toe Tap)"),
  ("Step Up","salita su rialzo"),
  ("WarmUp","riscaldamento"),
  ("Builder","programma strutturato"),
  ("native Strength","nativi di forza"),
  ("Coach Notes","note dell'allenatore"),
  ("reps","ripetizioni"),
 ]:t=t.replace(old,new)
 return t

def apply(workout,item):
 w=copy.deepcopy(workout)
 old_title=item["title"]
 name=new_title(old_title)
 must(w.get("workoutType")=="StructuredStrength"
      and w.get("title") in (old_title,name),"SOURCE_TITLE")
 must(w.get("prescribedDurationInSeconds")==item["planned_duration_seconds"],"SOURCE_DURATION")
 bs=w.get("blocks") or []
 must(len(bs)==len(item["native_exercises"])+2 and bs[0].get("blockType")=="WarmUp"
      and bs[-1].get("blockType")=="CoolDown","BLOCK_COUNT_OR_TYPE")
 if MARK in (bs[0].get("coachNotes") or ""):
  must(w.get("title")==name and len(bs[0].get("prescriptions") or [])==4,"PARTIAL_UPDATE_DRIFT")
  return w
 ids=[str((p.get("exercise") or {}).get("id")) for p in bs[0].get("prescriptions") or []]
 must(ids==["579","5184"],"OLD_WARMUP_NOT_EXPECTED")
 blocks=[warmup_block(item,bs[0])]
 for b,exercise in zip(bs[1:-1],item["native_exercises"]):
  q=copy.deepcopy(b)
  must(q.get("blockType")=="SingleExercise" and len(q.get("prescriptions") or [])==1
       and str(q["prescriptions"][0]["exercise"]["id"])==str(exercise["id"]),"MAIN_EXERCISE_DRIFT")
  q["title"]=IT.get(exercise["title"],exercise["title"])
  q["coachNotes"]=translate(q.get("coachNotes"))
  q["prescriptions"][0]["coachNotes"]=translate(q["prescriptions"][0].get("coachNotes"))
  blocks.append(q)
 last=copy.deepcopy(bs[-1])
 last["title"]="Controllo e mobilita del piede"
 last["coachNotes"]=translate(last.get("coachNotes"))
 for pr in last.get("prescriptions") or []:
  pr["coachNotes"]=translate(pr.get("coachNotes"))
 blocks.append(last)
 w["blocks"]=blocks
 w["title"]=name
 w["instructions"]=translate(w.get("instructions"))
 w["snapshot"]={**(w.get("snapshot") or {}),**_recount(blocks)}
 return w

def dose_blocks(workout):
 """Fingerprint of strength training ONLY, excl warmup and footcore."""
 result=[]
 for b in (workout.get("blocks") or [])[1:-1]:
  a=[]
  for p in b.get("prescriptions") or []:
   vals=[]
   for s in p.get("sets") or []:
    vals.append(tuple(sorted((str(z.get("parameter")),str(z.get("prescribedValue")))
                             for z in s.get("parameterValues") or [])))
   a.append((str((p.get("exercise") or {}).get("id")),tuple(vals)))
  result.append(tuple(a))
 return tuple(result)

def expected_shape(w,item):
 bs=w.get("blocks") or []
 if w.get("title")!=new_title(item["title"]) or w.get("workoutType")!="StructuredStrength":
  return False
 if w.get("prescribedDurationInSeconds")!=item["planned_duration_seconds"]:
  return False
 if len(bs)!=len(item["native_exercises"])+2:
  return False
 if MARK not in (bs[0].get("coachNotes") or ""):
  return False
 if [str((z.get("exercise") or {}).get("id")) for z in bs[0].get("prescriptions") or []]!=[z[0] for z in WARM_EX]:
  return False
 if any("Ponte per i glutei" in (p.get("coachNotes") or "") for p in bs[0].get("prescriptions") or []):
  return False
 if not all((b.get("prescriptions") or [{}])[0].get("coachNotes") for b in bs[1:-1]):
  return False
 return True

async def main():
 try:rows,plans=source_rows()
 except (OSError,ValueError,TypeError,KeyError) as exc:
  log(stage="SOURCE_STOP",reason=str(exc)[:180],writes=0);return 2
 async with TPClient() as c:
  me=await c._get_user_data()
  libs=await c.get("/exerciselibrary/v2/libraries")
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  must(not libs.is_error and isinstance(libs.data,list) and
       len([z for z in libs.data if z.get("exerciseLibraryId")==LIB and z.get("libraryName")==LIB_NAME and z.get("ownerId")==OWNER])==1,
       "WRONG_LIBRARY")
  must(not p.is_error and isinstance(p.data,dict) and
       p.data.get("planId")==PLAN and p.data.get("planPersonId")==PERSON and
       p.data.get("ownerPersonId")==OWNER and p.data.get("title")==PLAN_NAME and
       p.data.get("workoutCount")==16 and p.data.get("weekCount")==8 and
       p.data.get("isPublic") is False and p.data.get("price") in (0,None),
       "WRONG_PRIVATE_PLAN")
  _,token,err=await _access(c)
  must(not err and token,"NO_NATIVE_AUTH")
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   headers=_headers(token)
   async def library():
    rr=await h.get(STRENGTH_API_BASE+BASE+f"/libraryContent/workoutLibrary/{LIB}",headers=headers)
    must(rr.status_code==200,"LIBRARY_GET_HTTP_"+str(rr.status_code))
    raw=rr.json();x=raw if isinstance(raw,list) else raw.get("data") or []
    must(len(x)==35 and len({str(y.get("id")) for y in x})==35,"LIBRARY_ITEMS_DRIFT")
    return {str(y["id"]):y for y in x}
   async def planwork(id):
    rr=await h.get(STRENGTH_API_BASE+BASE+"/workouts/"+str(id),headers=headers)
    must(rr.status_code==200,"PLAN_DETAIL_"+str(id))
    return rr.json().get("data") or {}
   initial=await library()
   current_plan={}
   for item,slot in zip(rows,plans):
    original=initial.get(str(item["provider_item_id"]))
    must(original and original.get("workoutLibraryItemType")=="ActivityWorkoutTemplate"
         and original.get("title") in (item["title"],new_title(item["title"])),"LIB_TARGET_DRIFT")
    w=(original.get("workout") or {})
    must(w.get("calendarId") is None and w.get("prescribedDate") is None,"LIBRARY_DATED")
    olddose=dose_blocks(w)
    desired=apply(w,item)
    must(dose_blocks(desired)==olddose,"LIB_MAIN_DOSE_CHANGED")
    must(expected_shape(desired,item),"LIB_EXPECTED_SHAPE")
    actual=await planwork(slot["plan_native_workout_id"])
    must(str(actual.get("id"))==str(slot["plan_native_workout_id"]) and
         actual.get("calendarId")==PERSON and
         actual.get("title") in (item["title"],new_title(item["title"])) and
         actual.get("workoutType")=="StructuredStrength" and
         actual.get("prescribedDurationInSeconds")==item["planned_duration_seconds"],
         "PLAN_TARGET_DRIFT")
    must(dose_blocks(actual)==olddose,"LIB_PLAN_DOSE_NOT_EQUAL")
    must(dose_blocks(apply(actual,item))==olddose,"PLAN_MAIN_DOSE_CHANGED")
    current_plan[str(slot["plan_native_workout_id"])]=actual
   if not BACKUP.exists():
    BACKUP.parent.mkdir(parents=True,exist_ok=True)
    BACKUP.write_text(json.dumps({"plan":PLAN,"library":LIB,
          "original_lib_items":[initial[str(x["provider_item_id"])] for x in rows],
          "original_plan_items":current_plan},ensure_ascii=False,default=str)+"\n",encoding="utf-8")
   log(stage="PREFLIGHT_PASS",library_items=16,plan_instances=16,
       glute_bridge_warmup_removed=True,common_warmup_exercises=4,
       planned_duration_unchanged=True,main_dose_unchanged=True,
       work_remaining=16,writes=0)
   done=0
   for item,slot in zip(rows,plans):
    id_=str(item["provider_item_id"]);pid=str(slot["plan_native_workout_id"])
    # On partial completion, reconcile library and plan independently.
    before=await library()
    libitem=before[id_]
    oldw=libitem["workout"]
    target_lib=apply(oldw,item)
    if not expected_shape(oldw,item):
     payload={"id":int(id_),"libraryId":LIB,"title":target_lib["title"],
              "workout":target_lib,"workoutLibraryItemType":"ActivityWorkoutTemplate"}
     try:saved=await h.post(STRENGTH_API_BASE+BASE+"/libraryContent/workoutLibrary/save",
                            headers=headers,json=payload)
     except httpx.RequestError:
      log(stage="STOP_UNCERTAIN_LIBRARY_SAVE",id=id_,retry=False,done=done);return 4
     after=await library()
     got=after[id_]
     if saved.status_code!=200 or not expected_shape(got["workout"],item) or
        got["title"]!=new_title(item["title"]) or
        dose_blocks(got["workout"])!=dose_blocks(oldw):
      log(stage="STOP_LIBRARY_QA",id=id_,http=saved.status_code,done=done);return 4
    original_plan=await planwork(pid)
    updated_plan=apply(original_plan,item)
    if not expected_shape(original_plan,item):
     try:res=await h.post(STRENGTH_API_BASE+BASE+f"/plans/{PLAN}/workouts/save",
                           headers=headers,json=updated_plan)
     except httpx.RequestError:
      log(stage="STOP_UNCERTAIN_PLAN_SAVE",id=pid,retry=False,done=done);return 5
     confirmed=await planwork(pid)
     if (res.status_code!=200 or not expected_shape(confirmed,item) or
         confirmed.get("calendarId")!=PERSON or
         (confirmed.get("prescribedDate") or "")[:10]!=(original_plan.get("prescribedDate") or "")[:10]
         or dose_blocks(confirmed)!=dose_blocks(original_plan)):
      log(stage="STOP_PLAN_QA",id=pid,http=res.status_code,done=done);return 5
    done+=1
    log(stage="NATIVE_STRENGTH_WARMUP_AND_IT_VERIFIED",
        position=done,library_id=id_,plan_id=pid,new_title=new_title(item["title"]))
   end=await library()
   for item,slot in zip(rows,plans):
    pwork=await planwork(slot["plan_native_workout_id"])
    lw=end[str(item["provider_item_id"])]["workout"]
    must(expected_shape(lw,item) and expected_shape(pwork,item) and
         dose_blocks(pwork)==dose_blocks(lw) and
         pwork.get("calendarId")==PERSON and lw.get("calendarId") is None and
         pwork.get("prescribedDurationInSeconds")==lw.get("prescribedDurationInSeconds"),
         "FINAL_DOUBLE_READBACK_DRIFT")
   last=await c.get(f"/plans/v1/plans/{PLAN}")
   must(not last.is_error and last.data.get("workoutCount")==16 and
        last.data.get("isPublic") is False and last.data.get("weekCount")==8,
        "FINAL_PLAN_SCOPE")
   log(stage="WINTER8_WARMUP_AND_ITALIAN_16_OF_16_PROVIDER_VERIFIED",
       plan=PLAN,library=LIB,template_count=16,plan_count=16,
       warmup_exercise_ids=[x[0] for x in WARM_EX],main_dose_unchanged=True,
       planned_minutes=845,athlete_writes=0,duplicates=0)
   return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(main()))
 except Exception as exc:
  log(stage="SAFE_STOP",type=type(exc).__name__,reason=str(exc)[:190],retry=False)
  raise SystemExit(1)
