"""Read-only coverage audit of canonical Chasing 24W daily ledger against existing SW/BI/RU libraries."""
import asyncio,json,pathlib
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=685173
LIB={"SW":3891872,"BI":3892601,"RU":3892602}
FILE=pathlib.Path(__file__).resolve().parents[2]/"data/chasing_24w_day_ledger_20261012.json"
def log(**x):print(json.dumps(x,ensure_ascii=False),flush=True)
async def main():
 manifest=json.loads(FILE.read_text())
 if len(manifest["weeks"])!=24:return 2
 async with TPClient() as c:
  me=await c._get_user_data()
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  if not isinstance(me,dict) or me.get("personId")!=OWNER or p.is_error or p.data.get("isPublic") is not False:return 2
  source={}
  for kind,lib in LIB.items():
   r=await c.get(f"/exerciselibrary/v2/libraries/{lib}/items")
   if r.is_error or not isinstance(r.data,list):return 3
   source[kind]=r.data
  total=0;covered=0;ambiguous=0;missing=[]
  for week in manifest["weeks"]:
   for d in week["days"]:
    for kind in LIB:
     minutes=d.get(kind,0)
     if not minutes:continue
     total+=1
     candidates=[x for x in source[kind] if abs((x.get("totalTimePlanned") or 0)*60-minutes)<0.1 and x.get("itemName") and x.get("description")]
     if candidates:covered+=1
     if len(candidates)>1:ambiguous+=1
     if not candidates:missing.append({"week":week["week"],"day":d["day"],"sport":kind,"minutes":minutes})
  log(stage="COVERAGE",total=total,covered=covered,ambiguous=ambiguous,missing=missing)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
