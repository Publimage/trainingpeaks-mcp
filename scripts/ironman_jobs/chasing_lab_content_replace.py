"""Single sacrificial RUN in-place CONTENT replacement canary and restoration.
LAB plan 684206 only. Replace its 35min text RUN by existing native RUN 5km
template, read back complete native Builder, then RESTORE original. No Chasing writes.
"""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=684206
PERSON=6682479
RUN_ID=3994993213
LIB=3892602
TEMPLATE_ID=14947461
START="2027-06-21"
END="2027-06-28"
BACKUP=Path.home()/".trainingpeaks-mcp/lab_684206_run_5km_content_replace_backup.json"

def must(v,s):
 if not v:raise RuntimeError(s)
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def without_mod(x):return {k:v for k,v in x.items() if k not in ("lastModifiedDate",)}

async def snapshot(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_NOT_READABLE")
 z=p.data
 must(z.get("planId")==PLAN and z.get("isPublic") is False and z.get("workoutCount")==6 and
      str(z.get("startDate") or "")[:10]==START and z.get("price") in (None,0),"WRONG_LAB_SCOPE")
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
 must(not w.is_error and not n.is_error and isinstance(w.data,list) and isinstance(n.data,list)
      and len(w.data)==6 and len(n.data)==1,"LAB_CONTENT_CHANGED")
 return w.data,n.data

async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  must(isinstance(u,dict) and u.get("personId")==OWNER,"WRONG_OWNER")
  before,notes=await snapshot(c)
  original=[v for v in before if v.get("workoutId")==RUN_ID]
  must(len(original)==1 and original[0].get("workoutTypeValueId")==3
      and original[0].get("title")=="[MCP TEST] Run | Progressivo RPE 35'","WRONG_LAB_RUN")
  original=original[0]
  t=await c.get(f"/exerciselibrary/v2/libraries/{LIB}/items")
  must(not t.is_error and isinstance(t.data,list),"LIB_NOT_READABLE")
  template=[v for v in t.data if v.get("exerciseLibraryItemId")==TEMPLATE_ID]
  must(len(template)==1 and template[0].get("workoutTypeId")==3,"TEST_TEMPLATE_NOT_FOUND")
  template=template[0]
  must(isinstance(template.get("structure"),dict) and template.get("itemName")=="Test | 5 km - riferimento corsa","TEMPLATE_UNSTRUCTURED")
  must(not BACKUP.exists(),"PRIOR_CANARY_BACKUP_REVIEW_NO_RETRY")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"workout":original,"notes_sha":digest(notes),
    "other_workouts_sha":digest([x for x in before if x.get("workoutId")!=RUN_ID])},
    ensure_ascii=False,indent=2)+"\n")
  patched=dict(original)
  for a,b in [("title","itemName"),("description","description"),
              ("totalTimePlanned","totalTimePlanned"),("distancePlanned","distancePlanned"),
              ("structure","structure"),("workoutSubTypeId","workoutSubTypeId")]:
   patched[a]=template.get(b)
  print(json.dumps({"stage":"PREFLIGHT","plan":PLAN,"id":RUN_ID,
      "template_id":TEMPLATE_ID,"old_has_structure":original.get("structure") is not None,
      "new_has_structure":template.get("structure") is not None}),flush=True)
  endpoint=f"/plans/v1/plans/{PLAN}/workouts/{RUN_ID}"
  result=await c._request("PUT",endpoint,json=patched,_retry_on_401=False)
  try:
   after,notes_after=await snapshot(c)
   hit=[x for x in after if x.get("workoutId")==RUN_ID]
   must(len(hit)==1,"LAB_RUN_NOT_READ")
   x=hit[0]
   fields=["title","description","totalTimePlanned","distancePlanned",
           "structure","workoutSubTypeId"]
   match={k:x.get(k)==template.get({"title":"itemName"}.get(k,k)) for k in fields}
   print(json.dumps({"stage":"LAB_CONTENT_REPLACE_RESULT","write_error":result.is_error,
       "exact_fields":match,"native_builder_present":isinstance(x.get("structure"),dict),
       "same_workout_id":True,"other_workouts_preserved":digest([a for a in after if a.get("workoutId")!=RUN_ID])==digest([a for a in before if a.get("workoutId")!=RUN_ID]),
       "notes_preserved":digest(notes_after)==digest(notes)},ensure_ascii=False),flush=True)
  finally:
   live,_=await snapshot(c)
   cur=[a for a in live if a.get("workoutId")==RUN_ID]
   must(len(cur)==1,"LAB_RUN_MISSING_MANUAL_RESTORE")
   if without_mod(cur[0])!=without_mod(original):
    restored=await c._request("PUT",endpoint,json=original,_retry_on_401=False)
    must(not restored.is_error,"RESTORE_REJECTED_MANUAL_RECOVERY")
   final,notes_final=await snapshot(c)
   v=[a for a in final if a.get("workoutId")==RUN_ID]
   must(len(v)==1 and without_mod(v[0])==without_mod(original),"RESTORE_FIELDS_NOT_MATCHING")
   must(digest(notes_final)==digest(notes) and
        digest([a for a in final if a.get("workoutId")!=RUN_ID])==
        digest([a for a in before if a.get("workoutId")!=RUN_ID]),"RESTORE_NOTES_OR_OTHER_WORKOUTS_CHANGED")
   print(json.dumps({"stage":"LAB_RESTORED","original_run_restored":True,
      "other_workouts_and_notes_preserved":True}),flush=True)

if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as exc:
  print(json.dumps({"stage":"STOP","reason":str(exc)[:240],"no_blind_retry":True}),flush=True)
  raise
