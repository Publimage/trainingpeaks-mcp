"""Final guarded third native PDF attachment to Intermediate README FIRST.

Exact plan 684602, note 2653899, established JSON route from disposable test.
Preflight full note inventory and preexisting attachments, then one POST,
and post-readback 3/3 PDF check. No other plan/workout/note changes.
"""
import asyncio,base64,hashlib,json
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=684602
README=2653899
FIRST="2026-10-05"
END="2027-04-01"
TITLE="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
PDF=Path("/home/ironman/.local/state/ironman-operator/intermediate-guide-v3.pdf")
FILENAME="IRONMAN_Intermediate_24W_Guida_Atleta_v3_Verificata.pdf"
SHA="7759224d295123bfdab5203dd82dfc7822228b0a3e60885a6b1003a1b4d7c938"
PREVIOUS={(95193,"IRONMAN_Intermediate_24W_Guida_Settimana_per_Settimana_v1.0.pdf",169368),
          (95194,"IRONMAN_Intermediate_24W_Guida_Fueling_Nutrizione_v1.0.pdf",109724)}
class Stop(Exception):pass
def must(v,s):
 if not v:raise Stop(s)
def sign(n):
 return {(int(a["id"]),str(a["fileName"]),int(a["contentLength"]))
           for a in n.get("attachments",[])}
def note_id(n):return int(n.get("id") or n.get("calendarNoteId") or n.get("noteId"))
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(isinstance(me,dict) and me.get("personId")==OWNER,"OWNER_WRONG")
  async def get_plan():
   x=await c.get(f"/plans/v1/plans/{PLAN}")
   must(not x.is_error and isinstance(x.data,dict),"PLAN_READ_FAILED")
   return x.data
  async def get_notes():
   x=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{FIRST}/{END}")
   must(not x.is_error and isinstance(x.data,list),"NOTES_READ_FAILED")
   return x.data
  p=await get_plan()
  must((p.get("planId"),p.get("title"),p.get("weekCount"),p.get("workoutCount"))
      ==(PLAN,TITLE,24,259),"PLAN_SCOPE_CHANGED")
  must(p.get("isPublic") is False and p.get("price") in (None,0),"PLAN_VISIBILITY_CHANGED")
  must(p.get("startDate","")[:10]==FIRST and p.get("author") and p.get("planEmail"),"PLAN_METADATA_MISSING")
  before=await get_notes()
  must(len(before)==35 and len({note_id(n) for n in before})==35,"NOTES_CHANGED")
  first=[n for n in before if n.get("noteDate","")[:10]==FIRST]
  must([note_id(n) for n in first]==[README,2654983,2654984],"README_NOT_FIRST")
  original=first[0]
  must(original.get("title")=="README FIRST | INIZIA DA QUI" and len(original.get("description",""))>1600,"README_CHANGED")
  must(sign(original)==PREVIOUS,"TWO_ORIGINAL_PDFS_CHANGED")
  must(PDF.is_file() and PDF.stat().st_size==396936,"PDF_NOT_STAGED")
  data=PDF.read_bytes()
  must(hashlib.sha256(data).hexdigest()==SHA,"PDF_HASH_INVALID")
  payload={"planId":PLAN,"noteId":README,"fileName":FILENAME,
           "contentType":"application/pdf","data":base64.b64encode(data).decode("ascii")}
  await c._ensure_client()
  token=await c._ensure_access_token()
  must(token.success,"AUTH_MISSING")
  try:
   r=await c._client.request("POST",
    f"{c.base_url}/plans/v1/plans/{PLAN}/calendarNote/{README}/attachments",
    headers=c._get_headers(),json=payload,timeout=60)
  except Exception as ex:
   print("AMBIGUOUS_POST_STOP",type(ex).__name__,flush=True);return 2
  if r.status_code not in (200,201,204):
   print("POST_ERROR_STOP",r.status_code,r.text[:300],flush=True);return 2
  after=await get_notes()
  must(len(after)==35 and {note_id(n) for n in after}=={note_id(n) for n in before},
       "NOTE_INVENTORY_CHANGED")
  for n in before:
   if note_id(n)!=README:
    n2=next(x for x in after if note_id(x)==note_id(n))
    must(n2==n,f"OTHER_NOTE_CHANGED_{note_id(n)}")
  updated=next(n for n in after if note_id(n)==README)
  for k in ("id","title","description","noteDate","planId","createdDate"):
   must(updated.get(k)==original.get(k),f"README_FIELD_CHANGED_{k}")
  must(len(updated.get("attachments",[]))==3,"NOT_THREE_ATTACHMENTS")
  actual=sign(updated)
  must(PREVIOUS.issubset(actual),"ORIGINAL_TWO_LOST")
  fresh=[item for item in actual if item not in PREVIOUS]
  must(len(fresh)==1 and fresh[0][1]==FILENAME and fresh[0][2]==396936,"THIRD_PDF_MISMATCH")
  pp=await get_plan()
  must((pp.get("title"),pp.get("workoutCount"),pp.get("weekCount"),pp.get("isPublic"))
      ==(TITLE,259,24,False),"TRAINING_PLAN_MODIFIED")
  print("INTERMEDIATE_THIRD_NATIVE_PDF_ATTACHED_VERIFIED",json.dumps({
    "planId":PLAN,"title":TITLE,"readme_id":README,
    "attachment_count":3,"original_attachment_ids":[95193,95194],
    "new_attachment_id":fresh[0][0],"new_file_name":FILENAME,
    "new_file_bytes":396936,"sha256":SHA,"workouts":259,"notes":35,
    "readme_first":True,"other_34_notes_unchanged":True},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(main()))
 except Stop as e:print("STOP_REVIEW",str(e),flush=True);raise SystemExit(2)
