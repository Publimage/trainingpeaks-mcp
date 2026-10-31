"""Beginner 679801: migrate exactly 29 one-minute Other annotation cards to native CalendarNotes.
Preserve existing README native note, every real workout, plan public state and all text/placement.
Create+verify all native twins first; only then delete source Other cards one by one.
"""
import asyncio,copy,hashlib,json
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
P=679801; OWNER=2116886; EXPECT_WORKOUTS=254; EXPECT_OTHER=29; EXPECT_NATIVE_BEFORE=1
BASE=Path.home()/".trainingpeaks-mcp"
BACKUP=BASE/"beginner679801_other_to_native_notes_20261016_before.json"
def need(x,m):
 if not x: raise RuntimeError(m)
def nid(n): return int(n.get("id") or n.get("calendarNoteId") or n.get("noteId") or 0)
def wid(w): return int(w.get("workoutId") or w.get("planWorkoutId") or w.get("id") or 0)
def stable_workout(w):
 return {k:v for k,v in w.items() if k!="lastModifiedDate"}
def key_note(n):
 return ((n.get("title") or "").strip(),n.get("description") or "",str(n.get("noteDate") or n.get("date") or "")[:10])
def key_other(w):
 return ((w.get("title") or "").strip(),w.get("description") or "",str(w.get("workoutDay") or "")[:10])
def digest(v): return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
async def read_all(c,start,end):
 wr=await c.get(f"/plans/v1/plans/{P}/workouts/{start}/{end}")
 nr=await c.get(f"/plans/v1/plans/{P}/calendarNote/{start}/{end}")
 need(not wr.is_error and isinstance(wr.data,list),"WORKOUT_READ")
 need(not nr.is_error and isinstance(nr.data,list),"NOTE_READ")
 return wr.data,nr.data
async def main():
 async with TPClient() as c:
  me=await c._get_user_data(); need(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  h=await c.get(f"/plans/v1/plans/{P}"); need(not h.is_error and isinstance(h.data,dict),"PLAN_READ")
  p=h.data
  need(p.get("planId")==P and p.get("isPublic") is True and p.get("workoutCount")==EXPECT_WORKOUTS and p.get("weekCount")==24 and "Beginner" in (p.get("title") or ""),"PLAN_GUARD")
  start=str(p.get("startDate") or "")[:10]; need(start,"NO_START")
  end=(date.fromisoformat(start)+timedelta(weeks=24,days=2)).isoformat()
  workouts,notes=await read_all(c,start,end)
  others=[w for w in workouts if w.get("workoutTypeValueId")==100]
  real=[w for w in workouts if w.get("workoutTypeValueId")!=100]
  need(len(workouts)==EXPECT_WORKOUTS and len(others)==EXPECT_OTHER and len(real)==EXPECT_WORKOUTS-EXPECT_OTHER,"COUNT_GUARD")
  need(len(notes)==EXPECT_NATIVE_BEFORE,"NATIVE_NOTE_BASELINE_DRIFT")
  need((notes[0].get("title") or "").strip()=="README FIRST | INIZIA DA QUI","README_BASELINE_DRIFT")
  for w in others:
   need(wid(w)>0 and abs(float(w.get("totalTimePlanned") or 0)-1/60)<0.0001 and w.get("structure") is None,"OTHER_SHAPE_"+str(wid(w)))
   need((w.get("title") or "").strip() and (w.get("description") or "").strip() and str(w.get("workoutDay") or "")[:10],"OTHER_CONTENT_"+str(wid(w)))
  need(len({wid(w) for w in others})==EXPECT_OTHER,"OTHER_ID_DUP")
  need(len({key_other(w) for w in others})==EXPECT_OTHER,"OTHER_KEY_DUP")
  need(not ({key_other(w) for w in others}&{key_note(n) for n in notes}),"NATIVE_TWIN_ALREADY_EXISTS_UNEXPECTED")
  real_sig={wid(w):stable_workout(w) for w in real}
  other_sig={wid(w):stable_workout(w) for w in others}
  note_baseline=copy.deepcopy(notes)
  if BACKUP.exists():
   b=json.loads(BACKUP.read_text())
   need(b.get("plan")==P and len(b.get("others",{}))==EXPECT_OTHER,"BACKUP_SCOPE")
  else:
   BASE.mkdir(parents=True,exist_ok=True)
   BACKUP.write_text(json.dumps({"plan":P,"meta":p,"others":other_sig,"real_workouts":real_sig,"native_notes":notes},ensure_ascii=False,default=str,indent=2)+"\n")
  ordered=sorted(others,key=lambda w:(str(w.get("workoutDay") or "")[:10],wid(w)))
  expected_keys={key_note(n) for n in notes}
  print(json.dumps({"stage":"MIGRATION_PREFLIGHT_PASS","plan":P,"other_to_migrate":29,"native_before":1,"real_workouts":len(real)}),flush=True)
  created=0
  # Phase 1: create exact native twins; no source deletions yet.
  for w in ordered:
   k=key_other(w)
   _,cur_notes=await read_all(c,start,end)
   matches=[n for n in cur_notes if key_note(n)==k]
   if len(matches)==1:
    expected_keys.add(k); continue
   need(len(matches)==0,"DUPLICATE_NATIVE_TWIN_"+str(wid(w)))
   body={"planId":P,"title":w["title"],"noteDate":str(w["workoutDay"])[:10],"description":w["description"],"attachments":[]}
   res=await c._request("POST",f"/plans/v1/plans/{P}/calendarNote",json=body,_retry_on_401=False)
   # Reconcile provider state even if result is uncertain.
   _,after_notes=await read_all(c,start,end)
   matches=[n for n in after_notes if key_note(n)==k]
   need(len(matches)==1,"NATIVE_POST_UNVERIFIED_"+str(wid(w)))
   need(nid(matches[0])>0,"NATIVE_ID_MISSING_"+str(wid(w)))
   expected_keys.add(k); created+=1
   print(json.dumps({"stage":"NATIVE_NOTE_VERIFIED","source_workout_id":wid(w),"provider_note_id":nid(matches[0]),"created":created}),flush=True)
  workouts2,notes2=await read_all(c,start,end)
  need(len(notes2)==30 and {key_note(n) for n in notes2}==expected_keys,"NATIVE_SET_NOT_EXACT")
  need(len([w for w in workouts2 if w.get("workoutTypeValueId")==100])==29,"SOURCE_CHANGED_BEFORE_DELETE")
  need(all(stable_workout(w)==real_sig[wid(w)] for w in workouts2 if w.get("workoutTypeValueId")!=100),"REAL_WORKOUT_CHANGED_DURING_NOTE_CREATE")
  print(json.dumps({"stage":"ALL_NATIVE_NOTES_VERIFIED_BEFORE_DELETE","native_notes":30,"others_still_present":29}),flush=True)
  # Phase 2: delete exact source Other cards one-shot. Native twins already proven.
  deleted=0
  for w in ordered:
   ident=wid(w); k=key_other(w)
   current,cur_notes=await read_all(c,start,end)
   byid={wid(x):x for x in current}
   if ident not in byid:
    need(len([n for n in cur_notes if key_note(n)==k])==1,"MISSING_SOURCE_WITHOUT_NATIVE_"+str(ident))
    continue
   need(stable_workout(byid[ident])==other_sig[ident],"SOURCE_DRIFT_"+str(ident))
   need(len([n for n in cur_notes if key_note(n)==k])==1,"NATIVE_TWIN_MISSING_PREDELETE_"+str(ident))
   res=await c._request("DELETE",f"/plans/v1/plans/{P}/workouts/{ident}",_retry_on_401=False)
   after,after_notes=await read_all(c,start,end)
   ids={wid(x) for x in after}
   need(ident not in ids,"DELETE_NOT_VERIFIED_"+str(ident))
   need(len([n for n in after_notes if key_note(n)==k])==1,"NATIVE_TWIN_LOST_"+str(ident))
   need(all(stable_workout(x)==real_sig[wid(x)] for x in after if x.get("workoutTypeValueId")!=100),"REAL_WORKOUT_DRIFT_"+str(ident))
   deleted+=1
   print(json.dumps({"stage":"OTHER_DELETE_VERIFIED","source_workout_id":ident,"deleted":deleted}),flush=True)
  final,final_notes=await read_all(c,start,end)
  need(len(final)==225 and not any(w.get("workoutTypeValueId")==100 for w in final),"OTHER_REMAINS")
  need(len(final_notes)==30 and {key_note(n) for n in final_notes}==expected_keys,"FINAL_NOTE_SET_DRIFT")
  need(all(stable_workout(w)==real_sig[wid(w)] for w in final),"FINAL_REAL_WORKOUT_DRIFT")
  h2=await c.get(f"/plans/v1/plans/{P}")
  need(not h2.is_error and h2.data.get("workoutCount")==225 and h2.data.get("isPublic") is True,"FINAL_PLAN_META")
  print(json.dumps({"stage":"BEGINNER_NATIVE_NOTES_MIGRATION_VERIFIED","plan":P,"native_notes":30,"other_workouts":0,"real_workouts":225,"created_native_this_run":created,"deleted_other_this_run":deleted,"public_state_preserved":True}),flush=True)
if __name__=="__main__":
 try: asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"SAFE_STOP","reason":str(e)[:500]}),flush=True); raise
