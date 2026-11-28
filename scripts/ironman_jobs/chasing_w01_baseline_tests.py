"""CHASING W01 baseline tests: plan-scoped in-place replacement, 3 sport templates.
Run5km Monday after rest, Swim T1500 Tuesday, Bike20' Thursday. No new
workout rows, no athlete assignments. Native plan content PUT validated in LAB
684206 on rich structured RUN with restoration and notes preservation.
"""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient

OWNER=2116886
PERSON=6682479
PLAN=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
START="2027-01-04"
END="2027-01-10"
TEMPLATE_MAP=[
 {"id":4000490168,"date":"2027-01-04","sport":3,"old":"Aerobico | 40' facile con tecnica opzionale",
  "library":3892602,"item":14947461,"new":"Test | 5 km - riferimento corsa"},
 {"id":4000486945,"date":"2027-01-05","sport":1,"old":"Tecnica | 2500 m 6x50 + 4x350 facili",
  "library":3891872,"item":14945103,"new":"Test | T1500 iniziale - 2500 m"},
 {"id":4000490118,"date":"2027-01-07","sport":2,"old":"Aerobico | 85' fondo sotto LT1 e aero facoltativa",
  "library":3892601,"item":14963424,"new":"Test | 20' potenza sostenibile - 60'"},
]
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w01_baseline_tests_prepatch_backup.json"

def must(value,reason):
 if not value:raise RuntimeError(reason)
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
def no_metadata(v):return {k:vv for k,vv in v.items() if k not in ("lastModifiedDate",)}
async def snapshot(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_UNAVAILABLE")
 q=p.data
 must(q.get("planId")==PLAN and q.get("planPersonId")==PERSON
      and q.get("title")==TITLE and q.get("isPublic") is False and q.get("price") in (None,0)
      and q.get("workoutCount")==276 and str(q.get("startDate") or "")[:10]==START,
      "PLAN_SCOPE_DRIFT")
 r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
 must(not r.is_error and not n.is_error and isinstance(r.data,list) and isinstance(n.data,list)
      and len(r.data)==10 and len(n.data)==0,"W01_SOURCE_SLOTS_OR_NOTES_CHANGED")
 return r.data,digest(n.data)

async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_COACH")
  initial,note_sig=await snapshot(c)
  originals=[]
  for spec in TEMPLATE_MAP:
   found=[x for x in initial if x.get("workoutId")==spec["id"]]
   must(len(found)==1,"WORKOUT_ID_NOT_UNIQUE")
   x=found[0]
   must(x.get("title")==spec["old"] and x.get("workoutTypeValueId")==spec["sport"] and
        str(x.get("workoutDay") or "")[:10]==spec["date"],"WRONG_WORKOUT_ID_OR_SPORT")
   originals.append(x)
  original_ids=sorted(x.get("workoutId") for x in initial)
  template_cache={}
  for spec in TEMPLATE_MAP:
   key=spec["library"]
   if key not in template_cache:
    r=await c.get(f"/exerciselibrary/v2/libraries/{key}/items")
    must(not r.is_error and isinstance(r.data,list),f"LIBRARY_UNREADABLE_{key}")
    template_cache[key]=r.data
  targets=[]
  for spec in TEMPLATE_MAP:
   matches=[x for x in template_cache[spec["library"]] if x.get("exerciseLibraryItemId")==spec["item"]]
   must(len(matches)==1,"WRONG_TEMPLATE_ID")
   template=matches[0]
   must(template.get("workoutTypeId")==spec["sport"] and template.get("itemName")==spec["new"]
        and isinstance(template.get("structure"),dict) and template.get("description"),
        "TEMPLATE_NOT_APPROVED_STRUCTURE")
   targets.append(template)
  must(not BACKUP.exists(),"BACKUP_EXISTS_NO_RETRY")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":PLAN,"source_ids":original_ids,"notes_sha":note_sig,
    "original_workouts":initial,"template_ids":[t["exerciseLibraryItemId"] for t in targets]},
    ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"W01_BASELINE_PREFLIGHT","plan":PLAN,"count":10,
   "replacement_ids":[v["id"] for v in TEMPLATE_MAP],"all_templates_native":True}),flush=True)
  for index,(spec,old,t) in enumerate(zip(TEMPLATE_MAP,originals,targets)):
   current,_=await snapshot(c)
   live=[x for x in current if x.get("workoutId")==spec["id"]]
   must(len(live)==1 and live[0].get("title")==spec["old"],f"DRIFT_AT_{index}")
   payload=dict(old)
   for dest,source in [("title","itemName"),("description","description"),
       ("totalTimePlanned","totalTimePlanned"),("distancePlanned","distancePlanned"),
       ("structure","structure"),("workoutSubTypeId","workoutSubTypeId")]:
    payload[dest]=t.get(source)
   r=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{spec['id']}",
              json=payload,_retry_on_401=False)
   after,newnotes=await snapshot(c)
   hit=[x for x in after if x.get("workoutId")==spec["id"]]
   must(len(hit)==1 and not r.is_error,f"WRITE_{index}_NOT_READABLE_NO_RETRY")
   x=hit[0]
   for dest,source in [("title","itemName"),("description","description"),
        ("totalTimePlanned","totalTimePlanned"),("distancePlanned","distancePlanned"),
        ("structure","structure"),("workoutSubTypeId","workoutSubTypeId")]:
    must(x.get(dest)==t.get(source),f"FIELD_{dest}_NOT_VERIFIED_INDEX_{index}")
   must(str(x.get("workoutDay") or "")[:10]==spec["date"] and
        x.get("workoutTypeValueId")==spec["sport"],f"DATE_OR_SPORT_CHANGED_{index}")
   must(newnotes==note_sig and sorted(x.get("workoutId") for x in after)==original_ids,
        f"NOTES_OR_IDS_CHANGED_{index}")
   for y in after:
    oldy=next(z for z in initial if z.get("workoutId")==y.get("workoutId"))
    if y.get("workoutId")==spec["id"]:continue
    # Previous replacement(s) are allowed but ALL other original rows must retain identity/content.
    if any(v["id"]==y.get("workoutId") for v in TEMPLATE_MAP[:index]):continue
    must(no_metadata(y)==no_metadata(oldy),f"OTHER_ROW_CHANGED_{y.get('workoutId')}")
   print(json.dumps({"stage":"BASELINE_TEST_REPLACED","sport":spec["sport"],"date":spec["date"],
       "workout_id":spec["id"],"title":spec["new"],"native_builder":True}),flush=True)
  final,finalnotes=await snapshot(c)
  must(finalnotes==note_sig and len(final)==10 and
       sorted(x.get("workoutId") for x in final)==original_ids,"FINAL_INVARIANT")
  print(json.dumps({"stage":"W01_BASELINE_TESTS_PASS","plan":PLAN,"replacements":3,
     "swim_2500m":True,"bike_20min_60min_total":True,"run_5km":True,
     "same_workout_ids":True,"private":True,"strength_untouched":True,
     "notes_preserved":True,"no_athlete_calendar":True}),flush=True)

if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_W01_TESTS","reason":str(e)[:280],"no_blind_retry":True}),flush=True)
  raise
