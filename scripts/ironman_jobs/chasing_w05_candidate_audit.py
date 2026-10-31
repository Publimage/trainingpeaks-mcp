"""Read-only W05 candidate workout mapping, no writes."""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=685173
LIB={"SW":3891872,"BI":3892601,"RU":3892602}
DAYS=[(1,"SW",60),(1,"BI",105),(2,"SW",60),(2,"RU",85),(3,"BI",95),(3,"RU",50),(4,"SW",60),(4,"RU",35),(5,"BI",220),(6,"RU",20)]
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  if not isinstance(me,dict) or me.get("personId")!=OWNER or p.is_error or p.data.get("isPublic") is not False:return 2
  for kind,lib in LIB.items():
   r=await c.get(f"/exerciselibrary/v2/libraries/{lib}/items")
   if r.is_error or not isinstance(r.data,list):return 3
   for day,k,minutes in DAYS:
    if k!=kind:continue
    candidates=[{"id":x.get("exerciseLibraryItemId"),"name":x.get("itemName"),"meters":x.get("distancePlanned")} for x in r.data if abs((x.get("totalTimePlanned") or 0)*60-minutes)<0.1 and x.get("description")]
    print(json.dumps({"day":day,"sport":kind,"min":minutes,"candidates":candidates},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
