"""One-shot guarded native Strength plan LAB route test; never production."""
import asyncio,json,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,_build_payload,STRENGTH_API_BASE
PLAN=684543
TITLE="[MCP TEST] TP Native Strength Plan Route 2026-10-09"
NEW="[MCP TEST] Native Strength plan lab verified route 2026-10-12"
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  if u.get("personId")!=2116886 or p.is_error:return 2
  d=p.data
  if d.get("planId")!=PLAN or d.get("title")!=TITLE or d.get("isPublic") is not False or d.get("price") not in (None,0) or d.get("workoutCount")!=5 or (d.get("startDate") or "")[:10]!="2026-10-07":
   print(json.dumps({"stage":"STOP_SCOPE","count":d.get("workoutCount")}),flush=True);return 3
  _,token,err=await _access(c)
  if err:return 4
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   sr=await h.get(STRENGTH_API_BASE+"/rx/activity/v1/workouts/33903234",headers=_headers(token))
   if sr.status_code!=200:return 5
   source=sr.json().get("data") or {}
   if source.get("workoutType")!="StructuredStrength" or source.get("calendarId")!=6678164:return 6
   payload=_build_payload(6678164,"2027-08-06",NEW,[{"type":"SingleExercise","title":"Lab route verification","exercises":[{"id":"144","sets":[{"Reps":7}]}]}],"One lab-only Goblet Squat; no athlete calendar.")
   print(json.dumps({"stage":"PREFLIGHT","plan":PLAN,"count":5,"target":"2027-08-06"}),flush=True)
   try:res=await h.post(STRENGTH_API_BASE+f"/rx/activity/v1/plans/{PLAN}/workouts/save",json=payload,headers=_headers(token))
   except httpx.RequestError:
    print('{"stage":"AMBIGUOUS_POST","retry":false}',flush=True);return 7
   if res.status_code!=200:
    print(json.dumps({"stage":"PROVIDER_REJECTED","http":res.status_code}),flush=True);return 8
   data=res.json().get("data") or {}
   wid=str(data.get("id") or payload["id"])
   rr=await h.get(STRENGTH_API_BASE+"/rx/activity/v1/workouts/"+wid,headers=_headers(token))
   pp=await c.get(f"/plans/v1/plans/{PLAN}")
   found=rr.json().get("data") if rr.status_code==200 else {}
   ok=bool(found and found.get("title")==NEW and found.get("workoutType")=="StructuredStrength" and found.get("calendarId")==6678164 and not pp.is_error and pp.data.get("workoutCount")==6)
   print(json.dumps({"stage":"LAB_RESULT","ok":ok,"native_id":wid,"plan_count":pp.data.get("workoutCount") if not pp.is_error else None,"calendar":found.get("calendarId") if found else None}),flush=True)
   return 0 if ok else 9
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
