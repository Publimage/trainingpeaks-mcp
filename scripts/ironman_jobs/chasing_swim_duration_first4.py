"""Guarded in-place native Planned Duration repair for 11 Chasing swim plan instances.
Library items are already patched independently. Never delete/recreate workouts.
"""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=685173
PERSON=6682479
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
LIB=3891872
START="2027-01-04"
END="2027-01-31"
FIXES=[
(4000490051,14962929,55),(4000490159,14962930,55),
(4000490220,14962936,60),(4000490258,14962929,55),(4000490371,14962937,60),
(4000591453,14962936,60),(4000591488,14962939,60),(4000591562,14962937,60),
(4000591594,14963009,50),(4000591617,14963010,50),(4000591658,14963011,50)]
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_swim_duration_w01_w04_backup.json"
def must(v,msg):
 if not v:raise RuntimeError(msg)
def sha(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
def clean(v):return {k:x for k,x in v.items() if k not in ("totalTimePlanned","lastModifiedDate")}
async def snap(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_READ_FAILED")
 q=p.data
 must(q.get("planId")==PLAN and q.get("planPersonId")==PERSON and q.get("title")==TITLE
      and q.get("isPublic") is False and q.get("workoutCount")==276
      and str(q.get("startDate") or "")[:10]==START,"WRONG_PLAN_OR_DRIFT")
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
 must(not w.is_error and not n.is_error and isinstance(w.data,list) and isinstance(n.data,list)
      and len(w.data)==39,"PLAN_FIRST_4_WEEKS_DRIFT")
 return w.data,sha(n.data)
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  must(isinstance(u,dict) and u.get("personId")==OWNER,"WRONG_OWNER")
  before,notes=await snap(c)
  lib=await c.get(f"/exerciselibrary/v2/libraries/{LIB}/items")
  must(not lib.is_error and isinstance(lib.data,list),"LIBRARY_UNREADABLE")
  ids=sorted(x.get("workoutId") for x in before)
  refs=[]
  for wid,lid,minutes in FIXES:
   matches=[x for x in before if x.get("workoutId")==wid]
   templates=[x for x in lib.data if x.get("exerciseLibraryItemId")==lid]
   must(len(matches)==1 and len(templates)==1,f"ID_OR_TEMPLATE_MISSING_{wid}")
   item=matches[0];tmp=templates[0]
   must(item.get("workoutTypeValueId")==1 and item.get("title")==tmp.get("itemName")
        and abs((item.get("distancePlanned") or 0)-(tmp.get("distancePlanned") or 0))<0.01
        and isinstance(item.get("structure"),dict),"SPORT_TITLE_METRES_OR_BUILDER_CHANGED")
   must(item.get("totalTimePlanned") in (None,0),"SOURCE_ALREADY_HAS_DURATION_NO_REPEAT")
   must(abs((tmp.get("totalTimePlanned") or 0)*60-minutes)<0.01,
        f"LIBRARY_DURATION_NOT_VERIFIED_{lid}")
   refs.append(item)
  must(not BACKUP.exists(),"PRIOR_BACKUP_EXISTS_DO_NOT_BLIND_RETRY")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":PLAN,"original_workouts":before,
     "note_checksum":notes,"corrections":FIXES},ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"PREFLIGHT_PASS","plan":PLAN,"swims":len(FIXES),
                    "library_templates":len(set(x[1] for x in FIXES))}),flush=True)
  for wid,lid,minutes in FIXES:
   current,_=await snap(c)
   rows=[x for x in current if x.get("workoutId")==wid]
   must(len(rows)==1 and rows[0].get("totalTimePlanned") in (None,0),"PREFLIGHT_CHANGED_NO_RETRY")
   original=rows[0]
   patched=dict(original)
   patched["totalTimePlanned"]=minutes/60
   response=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",
                              json=patched,_retry_on_401=False)
   after,after_notes=await snap(c)
   v=[x for x in after if x.get("workoutId")==wid]
   must(len(v)==1 and not response.is_error,"PUT_UNVERIFIED")
   must(abs(v[0].get("totalTimePlanned",0)*60-minutes)<0.001,
        f"DURATION_NOT_PERSISTED_{wid}")
   must(clean(v[0])==clean(original),"NON_DURATION_FIELDS_CHANGED")
   must(sorted(x.get("workoutId") for x in after)==ids and after_notes==notes,
        "WORKOUT_IDS_OR_NOTES_CHANGED")
   print(json.dumps({"stage":"DURATION_VERIFIED","id":wid,"minutes":minutes,
       "metres":v[0].get("distancePlanned")}),flush=True)
  final,final_notes=await snap(c)
  all_swim=[x for x in final if x.get("workoutTypeValueId")==1]
  must(len(all_swim)==12 and all((x.get("totalTimePlanned") or 0)>0 for x in all_swim),
       "SWIM_12_OF_12_DURATION_GATE_FAIL")
  must(final_notes==notes and sorted(x.get("workoutId") for x in final)==ids,
       "GLOBAL_INTEGRITY_FAIL")
  print(json.dumps({"stage":"PASS_12_OF_12_W01_W04","repaired":11,"library_unique_updated":8,
     "all_metres_structures_and_ids_preserved":True,"private":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP","reason":str(e)[:270],"no_blind_retry":True}),flush=True)
  raise
