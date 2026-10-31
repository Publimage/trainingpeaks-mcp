"""Read-only native Strength plan laboratory state audit."""
import asyncio,json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  if u.get("personId")!=2116886:return 2
  p=await c.get("/plans/v1/plans/684543")
  if p.is_error:return 3
  d=p.data
  print(json.dumps({"plan":d.get("planId"),"title":d.get("title"),"count":d.get("workoutCount"),"start":d.get("startDate"),"public":d.get("isPublic")}),flush=True)
  _,token,err=await _access(c)
  if err:return 4
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   for path in ["/rx/activity/v1/workouts/33903234","/rx/activity/v1/workouts/calendar/684543/2027-08-01/2027-08-08"]:
    r=await h.get(STRENGTH_API_BASE+path,headers=_headers(token))
    v=r.json() if r.status_code==200 else {}
    d=v.get("data",v) if isinstance(v,dict) else v
    if isinstance(d,dict):out={"id":d.get("id"),"calendarId":d.get("calendarId"),"date":d.get("prescribedDate"),"title":d.get("title"),"type":d.get("workoutType")}
    elif isinstance(d,list):out=[{"id":x.get("id"),"calendarId":x.get("calendarId"),"date":x.get("prescribedDate"),"title":x.get("title")} for x in d if isinstance(x,dict)]
    else:out={}
    print(json.dumps({"path":path,"status":r.status_code,"data":out}),flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
