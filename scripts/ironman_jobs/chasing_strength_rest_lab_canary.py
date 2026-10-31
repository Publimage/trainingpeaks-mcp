"""Guarded sacrificial Coach Notes native library SAVE + exact restoration.
Never touches CHASING library, plan or athlete calendars.
"""
import asyncio,copy,json,httpx
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
OWNER=2116886;LIB=3890637;ID="330612"
BASE="/rx/activity/v1/libraryContent/workoutLibrary"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_strength_rest_lab_native_save_backup.json"
def must(x,s):
 if not x:raise RuntimeError(s)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  _,token,err=await _access(c)
  must(not err and token,"TOKEN_INVALID")
  headers=_headers(token)
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   async def get():
    r=await h.get(STRENGTH_API_BASE+BASE+f"/{LIB}",headers=headers)
    must(r.status_code==200,"GET_FAILED")
    obj=r.json()
    items=obj if isinstance(obj,list) else obj.get("data") or []
    matches=[v for v in items if str(v.get("id"))==ID]
    must(len(matches)==1,"LAB_ITEM_NOT_FOUND")
    item=matches[0]
    must(item.get("workoutLibraryItemType")=="ActivityWorkoutTemplate","WRONG_ITEM_TYPE")
    return item
   before=await get()
   original=before["workout"]
   must(original.get("calendarId") is None and original.get("prescribedDate") is None and
        original.get("workoutType")=="StructuredStrength","WRONG_LAB_RESOURCE")
   workout=copy.deepcopy(original)
   p=workout["blocks"][1]["prescriptions"][0]
   marker="\n[LAB REST NOTES CANARY — DELETE VIA RESTORE]"
   must(marker not in str(p.get("coachNotes")),"LAB_ALREADY_CHANGED")
   original_note=p.get("coachNotes")
   p["coachNotes"]=(original_note or "")+marker
   must(not BACKUP.exists(),"PREVIOUS_BACKUP_EXISTS_NO_RETRY")
   BACKUP.parent.mkdir(parents=True,exist_ok=True)
   BACKUP.write_text(json.dumps({"library":LIB,"item":before},ensure_ascii=False,indent=2)+"\n")
   payload={"id":int(ID),"libraryId":LIB,"title":before["title"],
      "workout":workout,"workoutLibraryItemType":"ActivityWorkoutTemplate"}
   print(json.dumps({"stage":"LAB_NOTE_PATCH_PREFLIGHT","lab":LIB,"id":ID}),flush=True)
   response=await h.post(STRENGTH_API_BASE+BASE+"/save",headers=headers,json=payload)
   try:
    now=await get()
    cur=now["workout"]["blocks"][1]["prescriptions"][0]["coachNotes"]
    must(response.status_code in (200,201) and cur==p["coachNotes"],"NATIVE_REST_NOTE_NOT_PERSISTED")
    print(json.dumps({"stage":"LAB_NOTE_PERSISTENCE_PASS","prescription_coachNotes":True}),flush=True)
   finally:
    check=await get()
    current=check["workout"]["blocks"][1]["prescriptions"][0]["coachNotes"]
    if current!=original_note:
     restore={"id":int(ID),"libraryId":LIB,"title":before["title"],"workout":original,
          "workoutLibraryItemType":"ActivityWorkoutTemplate"}
     rr=await h.post(STRENGTH_API_BASE+BASE+"/save",headers=headers,json=restore)
     must(rr.status_code in (200,201),"LAB_RESTORE_FAILED")
    end=await get()
    must(end["workout"]["blocks"][1]["prescriptions"][0]["coachNotes"]==original_note,
       "LAB_RESTORE_NOT_VERIFIED")
    print(json.dumps({"stage":"LAB_NOTES_RESTORED","same_item":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP","reason":str(e)[:210],"no_blind_retry":True}),flush=True)
  raise
