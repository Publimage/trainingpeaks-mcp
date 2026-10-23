"""Intermediate 684602 README description-only: identify current three guides while retaining all attachments.
No PDF deletion, no workout writes, no athlete/library writes.
"""
import asyncio,json
from tp_mcp.client import TPClient
PLAN=684602;NOTE=2653899;OWNER=2116886;PERSON=6678583
TITLE="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
BEFORE="I 3 PDF ALLEGATI — ORDINE DI LETTURA OBBLIGATORIO"
AFTER=("I 3 PDF CORRENTI — ORDINE DI LETTURA OBBLIGATORIO\n"
"Versioni da utilizzare:\n"
"- IRONMAN_Intermediate_24W_Guida_Atleta_v3.1_20261022.pdf\n"
"- IRONMAN_Intermediate_24W_Guida_Settimana_per_Settimana_v1.1.pdf\n"
"- IRONMAN_Intermediate_24W_Guida_Fueling_Nutrizione_v1.0.pdf\n"
"Le precedenti versioni Guida Atleta v3 e Guida settimanale v1.0, ancora elencate fra gli allegati, sono superate: non utilizzarle.")
ATT={
 95193:("IRONMAN_Intermediate_24W_Guida_Settimana_per_Settimana_v1.0.pdf",169368),
 95194:("IRONMAN_Intermediate_24W_Guida_Fueling_Nutrizione_v1.0.pdf",109724),
 95228:("IRONMAN_Intermediate_24W_Guida_Atleta_v3_Verificata.pdf",396936),
 98909:("IRONMAN_Intermediate_24W_Guida_Settimana_per_Settimana_v1.1.pdf",170439),
 98910:("IRONMAN_Intermediate_24W_Guida_Atleta_v3.1_20261022.pdf",968230)
}
def need(cond,msg):
 if not cond:raise RuntimeError(msg)
def aid(v):return int(v.get("id") or v.get("calendarNoteId") or 0)
def signature(note):
 return {int(a["id"]):(str(a["fileName"]),int(a["contentLength"])) for a in note.get("attachments") or []}
async def run():
 async with TPClient() as c:
  me=await c._get_user_data()
  need(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_COACH")
  async def get_plan():
   x=await c.get(f"/plans/v1/plans/{PLAN}")
   need(not x.is_error and isinstance(x.data,dict),"PLAN_GET_FAIL")
   v=x.data
   need((v.get("planId"),v.get("planPersonId"),v.get("ownerPersonId"),v.get("title"),v.get("weekCount"),v.get("workoutCount"),v.get("isPublic"),v.get("price"))==
        (PLAN,PERSON,OWNER,TITLE,24,259,True,179),"PLAN_SCOPE_DRIFT")
  async def get_notes():
   x=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/2026-10-05/2027-04-01")
   need(not x.is_error and isinstance(x.data,list) and len(x.data)==35,"NOTE_COUNT_DRIFT")
   ns={aid(v):v for v in x.data}
   need(len(ns)==35 and NOTE in ns,"NOTE_MEMBERSHIP")
   return ns
  await get_plan()
  ns=await get_notes()
  original=ns[NOTE]
  need(original.get("title")=="README FIRST | INIZIA DA QUI" and signature(original)==ATT,
       "README_OR_ATTACHMENTS_DRIFT")
  others={k:v for k,v in ns.items() if k!=NOTE}
  body=original.get("description") or ""
  if AFTER in body and BEFORE not in body:
   print(json.dumps({"stage":"README_CURRENT_GUIDES_ALREADY_VERIFIED","note":NOTE,
                     "attachments":len(ATT)}),flush=True)
   return
  need(body.count(BEFORE)==1 and AFTER not in body,"OLD_README_TEXT_DRIFT")
  payload=dict(original)
  payload["description"]=body.replace(BEFORE,AFTER)
  payload["planId"]=PLAN
  result=await c._request("PUT",f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE}",
                          json=payload,_retry_on_401=False)
  check=await get_notes()
  new=check[NOTE]
  need(new.get("description")==payload["description"] and signature(new)==ATT,
       "README_WRITE_NOT_VERIFIED")
  need({k:v for k,v in new.items() if k!="description"}==
       {k:v for k,v in original.items() if k!="description"},
       "README_FIELD_CHANGED")
  need(all(check[k]==v for k,v in others.items()),"ANOTHER_NOTE_CHANGED")
  await get_plan()
  print(json.dumps({"stage":"INTERMEDIATE_README_VERSION_NOTICE_VERIFIED","plan":PLAN,
                    "note":NOTE,"current_pdfs":[98910,98909,95194],
                    "obsolete_pdfs_retained":[95193,95228],
                    "pdf_attachment_total":5,"notes":35,"workouts":259,"price":179,
                    "athlete_writes":0,"library_writes":0},ensure_ascii=False),flush=True)
if __name__=="__main__":
 asyncio.run(run())
