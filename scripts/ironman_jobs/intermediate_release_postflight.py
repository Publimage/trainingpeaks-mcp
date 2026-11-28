"""Read-only independent postflight of Intermediate release name, 3 PDFs and cleanup.
No upload, delete, or provider writes. Print only IDs/titles/counts.
"""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=684602
README=2653899
TITLE="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
EXPECTED=[
 (95193,"IRONMAN_Intermediate_24W_Guida_Settimana_per_Settimana_v1.0.pdf",169368),
 (95194,"IRONMAN_Intermediate_24W_Guida_Fueling_Nutrizione_v1.0.pdf",109724),
 (95228,"IRONMAN_Intermediate_24W_Guida_Atleta_v3_Verificata.pdf",396936),
]
async def main():
 async with TPClient() as tp:
  me=await tp._get_user_data()
  assert isinstance(me,dict) and me.get("personId")==OWNER,"Wrong coach"
  p=await tp.get(f"/plans/v1/plans/{PLAN}")
  assert not p.is_error and isinstance(p.data,dict)
  x=p.data
  assert (x.get("planId"),x.get("title"),x.get("weekCount"),x.get("workoutCount"))==(PLAN,TITLE,24,259)
  assert x.get("isPublic") is False and x.get("price") in (None,0)
  assert x.get("author") and x.get("planEmail"),"Author or email missing"
  r=await tp.get(f"/plans/v1/plans/{PLAN}/calendarNote/2026-10-05/2027-04-01")
  assert not r.is_error and isinstance(r.data,list) and len(r.data)==35
  day=[n for n in r.data if n.get("noteDate","")[:10]=="2026-10-05"]
  assert [n.get("id") for n in day]==[README,2654983,2654984]
  n=day[0]
  assert n.get("title")=="README FIRST | INIZIA DA QUI" and len(n.get("description",""))==1671
  attachments=[(a.get("id"),a.get("fileName"),a.get("contentLength")) for a in n.get("attachments",[])]
  assert attachments==EXPECTED, "PDFs missing or wrong"
  q=await tp.get("/plans/v1/plans/684484/calendarNote/2027-07-05/2027-07-12")
  assert not q.is_error and isinstance(q.data,list)
  assert len(q.data)==1 and q.data[0].get("id")==2651317,"Signed link note not removed"
  print("FINAL_RELEASE_POSTFLIGHT_PASS",json.dumps({
   "plan_id":PLAN,"title":TITLE,"weeks":24,"workouts":259,
   "notes":35,"readme_first_id":README,
   "pdf_attachment_ids":[a[0] for a in attachments],
   "pdf_count":3,
   "pdf_v3_bytes":attachments[-1][2],
   "author_contact_present":True,
   "private_unpriced":True,
   "temp_signed_note_removed":True,
   "provider_writes":0},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
