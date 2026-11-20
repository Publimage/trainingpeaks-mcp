"""Read-only Swim Distance + Planned Duration universal gate: live coach Library and Plan.
Reusable underlying gate: tp_mcp.tools.swim_prescription_gate.
Do not publish if status BLOCK_RELEASE. No provider writes.
"""
from datetime import date,timedelta
import asyncio,json
from tp_mcp.client import TPClient
from tp_mcp.tools.swim_prescription_gate import audit_swims
OWNER=2116886
PLAN=685173
LIB=3891872
DATE=date(2027,1,4)
def at(days):return (DATE+timedelta(days=days)).isoformat()
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  if not isinstance(me,dict) or me.get("personId")!=OWNER: raise RuntimeError("WRONG_OWNER")
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  if p.is_error or not isinstance(p.data,dict) or p.data.get("isPublic") is not False or p.data.get("workoutCount")!=276:
   raise RuntimeError("TRAINING_PLAN_SCOPE_MISMATCH")
  x=await c.get(f"/exerciselibrary/v2/libraries/{LIB}/items")
  if x.is_error or not isinstance(x.data,list) or len(x.data)!=104:
   raise RuntimeError("LIBRARY_READ_OR_COUNT_MISMATCH")
  lib=audit_swims(x.data,surface=f"TrainingPeaks Library {LIB}")
  w=[]
  for k in range(6):
   a=at(k*28)
   b=at((k+1)*28-1)
   response=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{a}/{b}")
   if response.is_error or not isinstance(response.data,list):
    raise RuntimeError(f"PLAN_READ_FAIL_BLOCK_{k}")
   w.extend(response.data)
  plan=audit_swims(w,surface=f"TrainingPeaks Plan {PLAN}")
  if plan["swim_count"]!=71:
   raise RuntimeError("SWIM_COUNT_DRIFT")
  out={"stage":"UNIVERSAL_SWIM_FIELDS_LIVE_GATE","plan":PLAN,"library":LIB,
       "workout_library":lib,"training_plan":plan,"provider_write_count":0,
       "release_gate":"PASS" if lib["status"]==plan["status"]=="PASS" else "BLOCK_RELEASE"}
  print(json.dumps(out,ensure_ascii=False),flush=True)
  return 0 if out["release_gate"]=="PASS" else 8
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
