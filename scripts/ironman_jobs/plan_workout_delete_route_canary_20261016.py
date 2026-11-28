"""Disposable LAB only: verify plan-workout DELETE route on exact one-minute Other.
Leaves LAB 684484 with zero workouts if PASS; native notes must remain identical.
"""
import asyncio,json
from datetime import date,timedelta
from tp_mcp.client import TPClient
P=684484; OWNER=2116886; WID=3995256662
TITLE="[MCP TEST] IMINT24W-W01-MON-OTHER-01 | SETTIMANA 1 | Calibrazione e riferimenti"
START="2027-07-05"; END="2027-07-13"
def need(x,m):
 if not x: raise RuntimeError(m)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data(); need(me.get("personId")==OWNER,"WRONG_OWNER")
  h=await c.get(f"/plans/v1/plans/{P}"); need(not h.is_error and h.data.get("isPublic") is False and h.data.get("workoutCount")==1,"LAB_GUARD")
  wr=await c.get(f"/plans/v1/plans/{P}/workouts/{START}/{END}")
  nr=await c.get(f"/plans/v1/plans/{P}/calendarNote/{START}/{END}")
  need(not wr.is_error and isinstance(wr.data,list) and len(wr.data)==1,"LAB_WORKOUT_READ")
  need(not nr.is_error and isinstance(nr.data,list),"LAB_NOTE_READ")
  w=wr.data[0]; notes=json.dumps(nr.data,sort_keys=True,ensure_ascii=False)
  need(w.get("workoutId")==WID and w.get("workoutTypeValueId")==100 and w.get("title")==TITLE,"LAB_TARGET_DRIFT")
  need(abs(float(w.get("totalTimePlanned") or 0)-1/60)<0.0001 and w.get("structure") is None,"LAB_OTHER_SHAPE")
  r=await c._request("DELETE",f"/plans/v1/plans/{P}/workouts/{WID}",_retry_on_401=False)
  wr2=await c.get(f"/plans/v1/plans/{P}/workouts/{START}/{END}")
  nr2=await c.get(f"/plans/v1/plans/{P}/calendarNote/{START}/{END}")
  h2=await c.get(f"/plans/v1/plans/{P}")
  need(not r.is_error and not wr2.is_error and isinstance(wr2.data,list) and len(wr2.data)==0,"DELETE_NOT_VERIFIED")
  need(not nr2.is_error and json.dumps(nr2.data,sort_keys=True,ensure_ascii=False)==notes,"NOTES_CHANGED")
  need(not h2.is_error and h2.data.get("workoutCount")==0,"COUNT_NOT_ZERO")
  print(json.dumps({"stage":"PLAN_WORKOUT_DELETE_ROUTE_VERIFIED","plan":P,"deleted_id":WID,"remaining_workouts":0,"notes_preserved":len(nr2.data),"endpoint":f"/plans/v1/plans/{{plan_id}}/workouts/{{workout_id}}"},ensure_ascii=False),flush=True)
if __name__=="__main__":
 asyncio.run(main())
