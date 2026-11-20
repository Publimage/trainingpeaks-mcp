"""Read-only Chasing 24W library contract audit; no TrainingPeaks writes."""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=685173
LIB={"SW":3891872,"BI":3892601,"RU":3892602,"ST":3894341}
def log(**x):print(json.dumps(x,ensure_ascii=False,default=str),flush=True)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  if not isinstance(me,dict) or me.get("personId")!=OWNER:log(stage="STOP_OWNER");return 2
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  if p.is_error or not isinstance(p.data,dict) or p.data.get("isPublic") is not False:
   log(stage="STOP_PRIVATE_PLAN");return 2
  for kind,lib in LIB.items():
   r=await c.get(f"/exerciselibrary/v2/libraries/{lib}/items")
   if r.is_error or not isinstance(r.data,list):log(stage="STOP_LIBRARY",kind=kind);return 3
   log(stage="LIBRARY",kind=kind,count=len(r.data),samples=[{k:v for k,v in x.items() if k not in ("description","workoutStructure","structure","steps","workout") } for x in r.data[:3]])
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
