"""Rename EXACT private Intermediate 24w plan without touching any workouts or Notes.

Lab PUT route and rollback verified on disposable plan 684484. Fail closed on
unexpected state, title collision or provider mutation. Never touch athletes.
"""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=684602
OLD="[MCP TEST] IRONMAN Intermediate Assembly 24W"
NEW="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
FIRST="2026-10-05"
LAST="2027-04-01"
EXPECTED_ORDER=[2653899,2654983,2654984]
EXPECTED_PDFS={(95193,"IRONMAN_Intermediate_24W_Guida_Settimana_per_Settimana_v1.0.pdf",169368),
               (95194,"IRONMAN_Intermediate_24W_Guida_Fueling_Nutrizione_v1.0.pdf",109724)}
class Stop(Exception): pass
def must(ok,msg):
 if not ok: raise Stop(msg)
def idof(n): return int(n.get("id") or n.get("calendarNoteId") or n.get("noteId"))
def attachments(n): return {(int(a["id"]),a["fileName"],int(a["contentLength"])) for a in n.get("attachments",[])}
async def go():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  async def plan():
   r=await c.get(f"/plans/v1/plans/{PLAN}")
   must(not r.is_error and isinstance(r.data,dict),"PLAN_READ_FAIL")
   return r.data
  async def notes():
   r=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{FIRST}/{LAST}")
   must(not r.is_error and isinstance(r.data,list),"NOTES_READ_FAIL")
   return r.data
  p=await plan()
  must((p.get("planId"),p.get("title"),p.get("weekCount"),p.get("workoutCount"))
       ==(PLAN,OLD,24,259),"PLAN_SCOPE_MISMATCH")
  must(p.get("isPublic") is False and p.get("price") in (None,0) and p.get("startDate","")[:10]==FIRST,
       "PLAN_VISIBILITY_DRIFT")
  l=await c.get("/plans/v1/plans")
  must(not l.is_error and isinstance(l.data,list),"LIST_READ_FAIL")
  must(not any(v.get("title","").casefold()==NEW.casefold() for v in l.data),"TITLE_COLLISION")
  before=await notes()
  must(len(before)==35 and len({idof(n) for n in before})==35,"NOTES_COUNT_DRIFT")
  first=[n for n in before if n.get("noteDate","")[:10]==FIRST]
  must([idof(x) for x in first]==EXPECTED_ORDER,"README_NOT_FIRST")
  must(attachments(first[0])==EXPECTED_PDFS,"EXISTING_PDFS_CHANGED")
  saved=json.dumps(before,sort_keys=True)
  result=await c._request("PUT",f"/plans/v1/plans/{PLAN}",
                          json={"planId":PLAN,"title":NEW},_retry_on_401=False)
  if result.is_error:
   print("STOP_WRITE_RESULT_UNCLEAR",result.error_code,flush=True)
   return 2
  p2=await plan()
  must(p2.get("title")==NEW,"TITLE_READBACK_FAILED")
  core=("planId","workoutCount","weekCount","startDate","endDate","isPublic","price","dayCount")
  must({k:p2.get(k) for k in core}=={k:p.get(k) for k in core},"CORE_CHANGED")
  changed={k for k in set(p)|set(p2) if p.get(k)!=p2.get(k) and k!="title"}
  must(all(("modif" in k.lower() or "updat" in k.lower()) for k in changed),
       "UNEXPECTED_EXTRA_FIELD_CHANGES:"+",".join(sorted(changed)))
  n2=await notes()
  must(json.dumps(n2,sort_keys=True)==saved,"NOTES_OR_ATTACHMENTS_CHANGED")
  l2=await c.get("/plans/v1/plans")
  must(not l2.is_error and isinstance(l2.data,list),"LIST_RECHECK_FAIL")
  must(sum(v.get("planId")==PLAN and v.get("title")==NEW for v in l2.data)==1,"LIST_TITLE_NOT_UNIQUE")
  print("PLAN_RENAMED_VERIFIED",json.dumps({"id":PLAN,"title":NEW,"workouts":259,"weeks":24,"notes":35,
           "readme_first":EXPECTED_ORDER[0],"preserved_pdfs":2,"provider_extra_modified_fields":list(sorted(changed))},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(go()))
 except Stop as e:
  print("STOP_REVIEW",str(e),flush=True);raise SystemExit(2)
