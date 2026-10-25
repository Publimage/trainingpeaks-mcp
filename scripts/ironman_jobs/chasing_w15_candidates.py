"""Read-only W15 template choices for guarded assembly."""
import asyncio,json
from tp_mcp.client import TPClient
LIB={"SW":3891872,"BI":3892601,"RU":3892602}
NEEDS={"SW":[65],"BI":[120,175,300,140],"RU":[90,50,55,30]}
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  if u.get("personId")!=2116886:return 2
  for k,lib in LIB.items():
   r=await c.get(f"/exerciselibrary/v2/libraries/{lib}/items")
   if r.is_error:return 3
   for minutes in NEEDS[k]:
    a=[{"id":x.get("exerciseLibraryItemId"),"title":x.get("itemName"),"m":x.get("distancePlanned")} for x in r.data if abs((x.get("totalTimePlanned") or 0)*60-minutes)<.1 and x.get("description")]
    print(json.dumps({"sport":k,"minutes":minutes,"options":a},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
