"""Read-only Strength product preflight and plan calendar identity."""
import asyncio,json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  p=await c.get("/plans/v1/plans/685173")
  if u.get("personId")!=2116886 or p.is_error:return 2
  d=p.data
  print(json.dumps({"plan":d.get("planId"),"title":d.get("title"),"count":d.get("workoutCount"),"public":d.get("isPublic"),"price":d.get("price"),"start":d.get("startDate"),"calendarId":d.get("calendarId"),"planPersonId":d.get("planPersonId"),"ownerPersonId":d.get("ownerPersonId"),"keys":[k for k in d if "calendar" in k.lower() or "id" in k.lower()]}),flush=True)
  lab=await c.get("/plans/v1/plans/684543")
  if not lab.is_error:print(json.dumps({"labPlanPersonId":lab.data.get("planPersonId"),"labOwnerPersonId":lab.data.get("ownerPersonId")}),flush=True)
  _,token,err=await _access(c)
  if err:return 3
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   r=await h.get(STRENGTH_API_BASE+"/rx/activity/v1/libraryContent/workoutLibrary/3894341",headers=_headers(token))
   if r.status_code!=200:return 4
   v=r.json();items=v.get("data",v) if isinstance(v,dict) else v
   for x in items:
    if str(x.get("id")) in ("330618","330621","330624","330626","330628","330629","330631"):
     w=x.get("workout") or {}
     print(json.dumps({"id":x.get("id"),"title":x.get("title"),"type":w.get("workoutType"),"minutes":w.get("totalTimePlanned"),"blocks":len(w.get("blocks") or []),"calendarId":w.get("calendarId"),"workoutId":w.get("id"),"durationSeconds":w.get("prescribedDurationInSeconds"),"workoutKeys":list(w.keys()),"firstBlockKeys":list((w.get("blocks") or [{}])[0].keys())}),flush=True)
   cr=await h.get(STRENGTH_API_BASE+"/rx/activity/v1/workouts/calendar/6682479/2027-01-04/2027-01-20",headers=_headers(token))
   cv=cr.json() if cr.status_code==200 else []
   print(json.dumps({"calendar_status":cr.status_code,"calendar_count":len(cv) if isinstance(cv,list) else None}),flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
