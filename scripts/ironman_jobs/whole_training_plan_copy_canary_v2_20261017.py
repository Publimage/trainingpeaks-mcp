"""Guarded whole Training Plan COPY canary; cleanup uses already-proven whole-plan DELETE."""
from __future__ import annotations
import asyncio,json
from datetime import date,timedelta
from tp_mcp.client import TPClient
OWNER=2116886
SOURCE=684484
SOURCE_TITLE="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
COPY_TITLE="[MCP TEST] WHOLE PLAN COPY CANARY V2 2026-10-17"
PROTECTED={679801,684602,685173}
COPY_ROUTE="/plans/v1/commands/copyplan"
DELETE_ROUTE="/plans/v1/plans/{plan_id}"
class Stop(Exception):pass
def must(v,m):
 if not v:raise Stop(m)
def err(r):
 e=getattr(r,"error_code",None);return str(getattr(e,"value",e or "API_ERROR"))
async def plans(c):
 r=await c.get("/plans/v1/plans");must(not r.is_error and isinstance(r.data,list),"PLAN_LIST_FAILED")
 return [x for x in r.data if isinstance(x,dict)]
async def named(c,title):
 rows=[p for p in await plans(c) if (p.get("title") or "").strip()==title]
 must(len(rows)<=1,"DUPLICATE_TITLE");return rows[0] if rows else None
async def detail(c,pid):
 r=await c.get(f"/plans/v1/plans/{pid}");must(not r.is_error and isinstance(r.data,dict),"DETAIL_FAILED_"+err(r));return r.data
async def notes(c,pid,start):
 d0=date.fromisoformat(start[:10]);d1=d0+timedelta(days=14)
 r=await c.get(f"/plans/v1/plans/{pid}/calendarNote/{d0.isoformat()}/{d1.isoformat()}")
 must(not r.is_error and isinstance(r.data,list),"NOTES_READ_FAILED")
 return sorted([(x.get("title"),x.get("description"),(x.get("noteDate") or x.get("date") or "")[:10]) for x in r.data if isinstance(x,dict)])
async def go():
 async with TPClient() as c:
  me=await c._get_user_data();must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  base=await plans(c);base_ids={p.get("planId") for p in base}
  must(len(base_ids)==21 and PROTECTED.issubset(base_ids) and SOURCE in base_ids,"BASE_INVENTORY_CHANGED")
  must(await named(c,COPY_TITLE) is None,"COPY_TITLE_ALREADY_EXISTS")
  src=await detail(c,SOURCE)
  must(src.get("title")==SOURCE_TITLE and src.get("isPublic") is False and src.get("price") in (None,0),"SOURCE_SCOPE_CHANGED")
  must((src.get("workoutCount") or 0)==0 and src.get("weekCount")==1,"SOURCE_SHAPE_CHANGED")
  src_notes=await notes(c,SOURCE,src.get("startDate"))
  must(len(src_notes)==2,"SOURCE_NOTE_COUNT_CHANGED")
  payload={"planId":SOURCE,"title":COPY_TITLE,"planData":src}
  r=await c._request("POST",COPY_ROUTE,json=payload,_retry_on_401=False)
  pid=(r.data.get("planId") or r.data.get("id")) if not r.is_error and isinstance(r.data,dict) else None
  if not isinstance(pid,int) or pid<=0:
   row=await named(c,COPY_TITLE);must(row is not None,"COPY_AMBIGUOUS_NO_OBJECT");pid=row.get("planId")
  must(isinstance(pid,int) and pid>0 and pid not in PROTECTED and pid!=SOURCE,"COPY_ID_UNSAFE")
  seen=[]
  for _ in range(10):
   sr=await c.get(f"/plans/v1/plans/{pid}/planCopyStatus")
   if not sr.is_error:
    st=sr.data.get("status") if isinstance(sr.data,dict) else sr.data;seen.append(st)
    if st==2:break
   await asyncio.sleep(1)
  cp=await detail(c,pid)
  must(cp.get("title")==COPY_TITLE and cp.get("isPublic") is False and cp.get("price") in (None,0),"COPY_SCOPE_READBACK")
  must((cp.get("workoutCount") or 0)==0 and cp.get("weekCount")==src.get("weekCount"),"COPY_SHAPE_DRIFT")
  cp_notes=await notes(c,pid,cp.get("startDate"))
  must(cp_notes==src_notes,"COPY_NOTES_DRIFT")
  print(json.dumps({"stage":"WHOLE_PLAN_COPY_VERIFIED","source_plan_id":SOURCE,"copy_plan_id":pid,"copy_route":COPY_ROUTE,"status_route":"/plans/v1/plans/{new_plan_id}/planCopyStatus","status_seen":seen,"notes_verified":len(cp_notes)}),flush=True)
  dr=await c._request("DELETE",DELETE_ROUTE.format(plan_id=pid),_retry_on_401=False)
  # Never repeat DELETE. Provider list is authoritative for this lifecycle path.
  if dr.is_error and await named(c,COPY_TITLE) is not None:raise Stop("COPY_CLEANUP_UNCONFIRMED_"+err(dr))
  must(await named(c,COPY_TITLE) is None,"COPY_CLEANUP_LIST_STILL_PRESENT")
  final={p.get("planId") for p in await plans(c)}
  must(final==base_ids,"FINAL_INVENTORY_DRIFT")
  print(json.dumps({"stage":"WHOLE_PLAN_COPY_CANARY_PASS","provider_writes":2,"copy_route":COPY_ROUTE,"delete_route":DELETE_ROUTE,"protected_plans_touched":False,"athlete_calendar_writes":0}),flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(go()))
 except Stop as e:
  print(json.dumps({"stage":"STOP_REVIEW","reason":str(e),"never_blind_retry":True}),flush=True);raise SystemExit(2)
