"""Guarded whole Training Plan DELETE+COPY canary on disposable objects only."""
from __future__ import annotations
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
SOURCE=684484
SOURCE_TITLE="[MCP TEST] TP Plan DELETE Route Probe 2026-10-09"
DELETE_TITLE="[MCP TEST] WHOLE PLAN DELETE CANARY 2026-10-17"
COPY_TITLE="[MCP TEST] WHOLE PLAN COPY CANARY 2026-10-17"
PROTECTED={679801,684602,685173}
DELETE_ROUTE="/plans/v1/plans/{plan_id}"
COPY_ROUTE="/plans/v1/commands/copyplan"
class Stop(Exception):pass
def must(v,m):
 if not v: raise Stop(m)
def err(r):
 e=getattr(r,"error_code",None);return str(getattr(e,"value",e or "API_ERROR"))
async def plans(c):
 r=await c.get("/plans/v1/plans");must(not r.is_error and isinstance(r.data,list),"PLAN_LIST_FAILED")
 return [x for x in r.data if isinstance(x,dict)]
async def detail(c,pid):
 r=await c.get(f"/plans/v1/plans/{pid}")
 if r.is_error:
  if err(r)=="NOT_FOUND":return None
  raise Stop("DETAIL_FAILED_"+err(r))
 must(isinstance(r.data,dict),"DETAIL_SHAPE");return r.data
async def named(c,title):
 rows=[p for p in await plans(c) if (p.get("title") or "").strip()==title]
 must(len(rows)<=1,"DUPLICATE_CANARY_TITLE");return rows[0] if rows else None
async def create_empty(c):
 must(await named(c,DELETE_TITLE) is None,"DELETE_CANARY_ALREADY_EXISTS")
 r=await c._request("POST","/plans/v1/plans",json={"title":DELETE_TITLE,"weekCount":1,"dayCount":7,"isPublic":False},_retry_on_401=False)
 pid=(r.data.get("planId") or r.data.get("id")) if not r.is_error and isinstance(r.data,dict) else None
 if not isinstance(pid,int) or pid<=0:
  row=await named(c,DELETE_TITLE);must(row is not None,"CREATE_AMBIGUOUS_NO_OBJECT");pid=row.get("planId")
 must(isinstance(pid,int) and pid>0 and pid not in PROTECTED and pid!=SOURCE,"CREATE_ID_UNSAFE")
 p=await detail(c,pid);must(p and p.get("title")==DELETE_TITLE,"CREATE_READBACK")
 must(p.get("isPublic") is False and p.get("price") in (None,0) and (p.get("workoutCount") or 0)==0,"CREATE_NOT_EMPTY_PRIVATE")
 return pid
async def delete_once(c,pid,title):
 must(pid not in PROTECTED and pid!=SOURCE,"DELETE_PROTECTED")
 p=await detail(c,pid);must(p and p.get("title")==title and p.get("isPublic") is False and p.get("price") in (None,0),"DELETE_SCOPE")
 r=await c._request("DELETE",DELETE_ROUTE.format(plan_id=pid),_retry_on_401=False)
 if r.is_error and await named(c,title) is not None: raise Stop("DELETE_UNCONFIRMED_"+err(r))
 must(await named(c,title) is None,"DELETE_LIST_READBACK")
 must(await detail(c,pid) is None,"DELETE_DETAIL_STILL_EXISTS")
async def copy_source(c):
 must(await named(c,COPY_TITLE) is None,"COPY_CANARY_ALREADY_EXISTS")
 src=await detail(c,SOURCE)
 must(src and src.get("planId")==SOURCE and src.get("title")==SOURCE_TITLE,"SOURCE_SCOPE_CHANGED")
 must(src.get("isPublic") is False and src.get("price") in (None,0) and (src.get("workoutCount") or 0)==0,"SOURCE_NOT_DISPOSABLE")
 payload={"planId":SOURCE,"title":COPY_TITLE,"planData":src}
 r=await c._request("POST",COPY_ROUTE,json=payload,_retry_on_401=False)
 pid=(r.data.get("planId") or r.data.get("id")) if not r.is_error and isinstance(r.data,dict) else None
 if not isinstance(pid,int) or pid<=0:
  row=await named(c,COPY_TITLE);must(row is not None,"COPY_AMBIGUOUS_NO_OBJECT");pid=row.get("planId")
 must(isinstance(pid,int) and pid>0 and pid not in PROTECTED and pid!=SOURCE,"COPY_ID_UNSAFE")
 seen=[]
 for _ in range(8):
  sr=await c.get(f"/plans/v1/plans/{pid}/planCopyStatus")
  if not sr.is_error:
   st=sr.data.get("status") if isinstance(sr.data,dict) else sr.data;seen.append(st)
   if st==2:break
  await asyncio.sleep(1)
 cp=await detail(c,pid);must(cp and cp.get("title")==COPY_TITLE,"COPY_READBACK")
 must(cp.get("isPublic") is False and cp.get("price") in (None,0) and (cp.get("workoutCount") or 0)==0,"COPY_NOT_PRIVATE_EMPTY")
 for k in ("weekCount","dayCount","planCategory","description"):must(cp.get(k)==src.get(k),"COPY_DRIFT_"+k)
 print(json.dumps({"stage":"WHOLE_PLAN_COPY_VERIFIED","copy_plan_id":pid,"copy_status_seen":seen,"copy_route":COPY_ROUTE}),flush=True)
 return pid
async def go():
 async with TPClient() as c:
  me=await c._get_user_data();must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
  base=await plans(c);ids={p.get("planId") for p in base};must(PROTECTED.issubset(ids),"PROTECTED_INVENTORY_CHANGED")
  d=await create_empty(c);await delete_once(c,d,DELETE_TITLE)
  print(json.dumps({"stage":"WHOLE_PLAN_DELETE_VERIFIED","deleted_plan_id":d,"delete_route":DELETE_ROUTE}),flush=True)
  cp=await copy_source(c);await delete_once(c,cp,COPY_TITLE)
  final={p.get("planId") for p in await plans(c)};must(final==ids,"FINAL_PLAN_INVENTORY_DRIFT")
  print(json.dumps({"stage":"WHOLE_PLAN_LIFECYCLE_CANARY_PASS","provider_writes":4,"protected_plans_touched":False,"athlete_calendar_writes":0,"delete_route":DELETE_ROUTE,"copy_route":COPY_ROUTE}),flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(go()))
 except Stop as e:
  print(json.dumps({"stage":"STOP_REVIEW","reason":str(e),"never_blind_retry":True}),flush=True);raise SystemExit(2)
