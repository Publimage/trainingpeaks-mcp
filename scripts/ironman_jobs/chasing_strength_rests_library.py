"""One-pass guarded update of seven native CHASING Strength library templates.
Only Coach Notes for recoveries between sets and successive exercises.
No session time, sets, reps, load, RIR, dates or athlete plan updates.
"""
import asyncio,json,httpx,copy
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
from chasing_strength_rests_common import LIB_ID,apply,assert_correct,MARKER
OWNER=2116886; LIB=3894341
BASE="/rx/activity/v1/libraryContent/workoutLibrary"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_strength_rests_library_v1_backup.json"
ORDER=["M30","D40","M45","M60","A60","B60","S60"]
def must(b,r):
 if not b:raise RuntimeError(r)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  lr=await c.get("/exerciselibrary/v2/libraries")
  must(not lr.is_error and isinstance(lr.data,list),"LIBRARY_REGISTRY_UNREADABLE")
  found=[x for x in lr.data if x.get("exerciseLibraryId")==LIB]
  must(len(found)==1 and found[0].get("ownerId")==OWNER and
       found[0].get("libraryName")=="CHASING THE SLOT | Forza","WRONG_LIBRARY")
  _,token,err=await _access(c)
  must(not err and token,"NO_TOKEN")
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   async def read():
    rr=await h.get(STRENGTH_API_BASE+BASE+f"/{LIB}",headers=_headers(token))
    must(rr.status_code==200,"GET_LIB_FAILED")
    raw=rr.json(); data=raw if isinstance(raw,list) else raw.get("data") or []
    must(isinstance(data,list) and len(data)==7 and
         {str(x.get("id")) for x in data}==set(LIB_ID.values()),"LIBRARY_DRIFT")
    return {str(x["id"]):x for x in data}
   before=await read()
   for k,id in LIB_ID.items():
    item=before[id];w=item.get("workout") or {}
    must(item.get("workoutLibraryItemType")=="ActivityWorkoutTemplate" and
         w.get("workoutType")=="StructuredStrength" and w.get("calendarId") is None and
         w.get("prescribedDate") is None and w.get("prescribedDurationInSeconds") is None and
         f"Forza {k} " in item.get("title",""),"NON_TARGET_STRENGTH_TEMPLATE")
    must(all(MARKER not in str(p.get("coachNotes") or "") for b in w.get("blocks") or []
         for p in b.get("prescriptions") or []),"SOME_REST_ALREADY_PRESENT_NO_REPEAT")
    apply(w,k)
   must(not BACKUP.exists(),"BACKUP_ALREADY_EXISTS_NO_BLIND_RETRY")
   BACKUP.parent.mkdir(parents=True,exist_ok=True)
   BACKUP.write_text(json.dumps({"library":LIB,"original_items":list(before.values())},
                    ensure_ascii=False,indent=2)+"\n")
   print(json.dumps({"stage":"PREFLIGHT","seven_native":7,"duration_writes":0,
        "notes_only":True}),flush=True)
   for k in ORDER:
    id=LIB_ID[k]
    now=await read()
    actual=now[id]
    original=before[id]
    must(actual.get("title")==original.get("title"),"PREWRITE_TITLE_DRIFT")
    patch=apply(actual["workout"],k)
    payload={"id":int(id),"libraryId":LIB,"title":actual["title"],
              "workout":patch,"workoutLibraryItemType":"ActivityWorkoutTemplate"}
    response=await h.post(STRENGTH_API_BASE+BASE+"/save",headers=_headers(token),json=payload)
    after=await read()
    must(response.status_code in (200,201),"PROVIDER_WRITE_STATUS_UNCERTAIN")
    must(after[id].get("title")==original["title"] and
         after[id].get("workoutLibraryItemType")=="ActivityWorkoutTemplate",
         "TITLE_OR_TYPE_CHANGED")
    assert_correct(actual["workout"],after[id]["workout"],k)
    # Nothing else in the library can change as a side effect.
    for other,pre in now.items():
     if other!=id:
      must(after[other].get("title")==pre.get("title") and
           after[other].get("workout")==pre.get("workout"),"UNRELATED_TEMPLATE_CHANGED")
    print(json.dumps({"stage":"LIBRARY_REST_VERIFIED","variant":k,"item":id,
       "exercise_blocks":len(patch["blocks"])-1,"same_structure":True,
       "duration_unchanged":True}),flush=True)
   final=await read()
   must(all(any(MARKER in str(p.get("coachNotes") or "") for p in
       (final[LIB_ID[k]]["workout"]["blocks"][1].get("prescriptions") or []))
       for k in LIB_ID),"FINAL_NOTES_MISSING")
   print(json.dumps({"stage":"STRENGTH_REST_LIBRARY_PASS","count":7,
        "recreated":0,"duration_fields_changed":0,"athlete_calendar_writes":0}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_NO_RETRY","reason":str(e)[:270]}),flush=True)
  raise
