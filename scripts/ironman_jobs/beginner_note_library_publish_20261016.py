"""Publish exact live Beginner 679801 native CalendarNotes as native NoteTemplates
into plan-exclusive library FIRST IRONMAN 24W | Note | IT (3901898).
No plan/calendar/athlete writes.
"""
import asyncio,json
from tp_mcp.client import TPClient
P=679801; OWNER=2116886; LIB=3901898; LIB_NAME="FIRST IRONMAN 24W | Note | IT"
def need(x,m):
 if not x: raise RuntimeError(m)
def nkey(n): return ((n.get("title") or "").strip(), n.get("description") or "")
def ikey(i): return ((i.get("itemName") or "").strip(), i.get("description") or "")
async def main():
 async with TPClient() as c:
  me=await c._get_user_data(); need(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  libs=await c.get("/exerciselibrary/v2/libraries")
  need(not libs.is_error and isinstance(libs.data,list),"LIBRARIES_READ")
  row=next((x for x in libs.data if x.get("exerciseLibraryId")==LIB),None)
  need(row and row.get("libraryName")==LIB_NAME and row.get("ownerId")==OWNER,"LIB_GUARD")
  h=await c.get(f"/plans/v1/plans/{P}"); need(not h.is_error and h.data.get("isPublic") is True and h.data.get("workoutCount")==225,"PLAN_GUARD")
  p=h.data; start=str(p.get("startDate") or "")[:10]
  from datetime import date,timedelta
  end=(date.fromisoformat(start)+timedelta(weeks=24,days=2)).isoformat()
  nr=await c.get(f"/plans/v1/plans/{P}/calendarNote/{start}/{end}")
  need(not nr.is_error and isinstance(nr.data,list) and len(nr.data)==30,"NOTE_SOURCE_GUARD")
  notes=nr.data
  need(sum(1 for n in notes if (n.get("title") or "").strip()=="README FIRST | INIZIA DA QUI")==1,"README_SOURCE")
  need(len({nkey(n) for n in notes})==30,"DUPLICATE_EXACT_SOURCE_NOTE")
  async def items():
   r=await c.get(f"/exerciselibrary/v2/libraries/{LIB}/items")
   need(not r.is_error and isinstance(r.data,list),"LIB_ITEMS_READ")
   return r.data
  before=await items()
  approved={nkey(n) for n in notes}
  need(all(i.get("exerciseLibraryItemType")=="NoteTemplate" and i.get("workoutTypeId")==0 and ikey(i) in approved for i in before),"UNRELATED_OR_WRONG_TYPE_IN_LIBRARY")
  created=0
  for n in notes:
   k=nkey(n)
   cur=await items()
   matches=[i for i in cur if ikey(i)==k]
   need(len(matches)<=1,"DUPLICATE_EXACT_LIBRARY_ITEM")
   if len(matches)==1:
    need(matches[0].get("exerciseLibraryItemType")=="NoteTemplate" and matches[0].get("workoutTypeId")==0,"WRONG_EXISTING_TYPE")
    continue
   payload={"exerciseLibraryId":LIB,"exerciseLibraryItemType":"NoteTemplate","itemName":n["title"],"workoutTypeId":0,"description":n["description"]}
   res=await c.post(f"/exerciselibrary/v1/libraries/{LIB}/items",json=payload)
   after=await items()
   matches=[i for i in after if ikey(i)==k]
   need(len(matches)==1,"NOTETEMPLATE_POST_UNVERIFIED")
   need(matches[0].get("exerciseLibraryItemType")=="NoteTemplate" and matches[0].get("workoutTypeId")==0,"NOTETEMPLATE_TYPE_MISMATCH")
   created+=1
   print(json.dumps({"stage":"NOTE_TEMPLATE_VERIFIED","created":created,"title":n["title"],"item_id":matches[0].get("exerciseLibraryItemId")},ensure_ascii=False),flush=True)
  final=await items()
  need(len(final)==30 and {ikey(i) for i in final}==approved,"FINAL_LIBRARY_SET_DRIFT")
  need(all(i.get("exerciseLibraryItemType")=="NoteTemplate" and i.get("workoutTypeId")==0 for i in final),"FINAL_TYPE_DRIFT")
  print(json.dumps({"stage":"BEGINNER_NOTE_LIBRARY_VERIFIED","library_id":LIB,"library_name":LIB_NAME,"native_note_templates":30,"created_this_run":created,"plan_writes":0,"athlete_writes":0},ensure_ascii=False),flush=True)
if __name__=="__main__":
 try: asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"SAFE_STOP","reason":str(e)[:500]}),flush=True); raise
