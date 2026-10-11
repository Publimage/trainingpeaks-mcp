"""Guarded README FIRST body-only update in the private 24-week Intermediate plan.

Disposable LAB Note PUT with binary attachment was independently verified.
Preserve three PDF binaries, 34 other notes, note order, and all 259 workouts.
Manifest is exact stored old/new content; abort if provider deviated.
"""
import asyncio,json
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=684602
NOTE=2653899
TITLE="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
MANIFEST=Path(__file__).resolve().parents[2]/"data/intermediate_readme_guide_order_v2.json"
PDFS={(95193,"IRONMAN_Intermediate_24W_Guida_Settimana_per_Settimana_v1.0.pdf",169368),
      (95194,"IRONMAN_Intermediate_24W_Guida_Fueling_Nutrizione_v1.0.pdf",109724),
      (95228,"IRONMAN_Intermediate_24W_Guida_Atleta_v3_Verificata.pdf",396936)}
class Stop(Exception):pass
def must(x,why):
 if not x:raise Stop(why)
def signature(n):
 return {(int(a["id"]),str(a["fileName"]),int(a["contentLength"])) for a in n.get("attachments",[])}
async def main():
 manifest=json.loads(MANIFEST.read_text("utf8"))
 must(manifest["plan_id"]==PLAN and manifest["plan_note_id"]==NOTE and
      manifest["library_id"]==3892900 and manifest["library_item_id"]==14951945,
      "MANIFEST_NOT_THIS_PLAN")
 old=manifest["old_body"];new=manifest["new_body"]
 must(len(old)==1671 and len(new)>len(old)+500 and "1. GUIDA ATLETA INTERMEDIATE 24W" in new,
      "CONTENT_MANIFEST_INVALID")
 prefix,suffix=old.split("PRIMA DI INIZIARE\\n".replace("\\\\n","\\n"),1)
 must(new.startswith(prefix) and new.endswith(suffix) and new.count("1. GUIDA ATLETA INTERMEDIATE 24W")==1,
      "ORIGINAL_CONTENT_NOT_PRESERVED")
 async with TPClient() as c:
  owner=await c._get_user_data()
  must(isinstance(owner,dict) and owner.get("personId")==OWNER,"WRONG_COACH")
  async def plan():
   r=await c.get(f"/plans/v1/plans/{PLAN}")
   must(not r.is_error and isinstance(r.data,dict),"PLAN_READ_FAILED")
   return r.data
  async def notes():
   r=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2026-10-05/2027-04-01")
   must(not r.is_error and isinstance(r.data,list),"NOTES_READ_FAILED")
   return r.data
  p=await plan()
  must((p.get("planId"),p.get("title"),p.get("workoutCount"),p.get("weekCount"))
       ==(PLAN,TITLE,259,24) and p.get("isPublic") is False and
       p.get("price") in (None,0),"WRONG_PLAN_OR_STRUCTURE")
  before=await notes()
  must(len(before)==35 and len({x.get("id") for x in before})==35,
       "NOTES_COUNT_WRONG")
  monday=[x for x in before if x.get("noteDate","")[:10]=="2026-10-05"]
  must([x["id"] for x in monday]==[2653899,2654983,2654984],
       "README_NOT_FIRST")
  original=monday[0]
  must(original.get("title")==manifest["title"] and
       original.get("description")==old and original.get("planId")==PLAN,
       "README_CONTENT_DRIFT")
  must(signature(original)==PDFS,"ATTACHMENTS_DRIFT")
  other={int(n["id"]):n for n in before if n["id"]!=NOTE}
  payload=dict(original)
  payload["description"]=new
  payload["planId"]=PLAN
  response=await c._request("PUT",f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}",
                            json=payload,_retry_on_401=False)
  if response.is_error:
   print("STOP_PUT_FAILED",str(response.error_code),flush=True)
   return 2
  after=await notes()
  must(len(after)==35 and {n["id"] for n in after}=={n["id"] for n in before},
       "NOTES_MEMBERSHIP_CHANGED")
  must(all(next(n for n in after if n["id"]==k)==n for k,n in other.items()),
       "ANOTHER_NOTE_MODIFIED")
  updated=next(n for n in after if n["id"]==NOTE)
  must(updated.get("title")==original.get("title") and
       updated.get("description")==new and
       updated.get("noteDate")==original.get("noteDate") and
       updated.get("planId")==PLAN and
       updated.get("createdDate")==original.get("createdDate"),
       "README_NON_DESCRIPTION_FIELD_CHANGED")
  must(signature(updated)==PDFS,"README_PDF_ATTACHMENTS_CHANGED")
  pp=await plan()
  must(pp.get("workoutCount")==259 and pp.get("weekCount")==24
       and pp.get("title")==TITLE,"PLAN_CHANGED")
  print("README_FIRST_GUIDE_ORDER_UPDATED_VERIFIED",json.dumps({
   "planId":PLAN,"noteId":NOTE,"guide_first":True,
   "body_length_before":len(old),"body_length_after":len(new),
   "three_pdf_ids":[95193,95194,95228],"other_34_notes_unchanged":True,
   "workouts":259,"weeks":24,"notes":35},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(main()))
 except Stop as e:
  print("STOP_REVIEW",str(e),flush=True);raise SystemExit(2)
