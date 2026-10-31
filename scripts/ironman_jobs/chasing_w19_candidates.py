"""Read-only W19 template choices for guarded assembly."""
import asyncio,json
from tp_mcp.client import TPClient
LIB={"SW":3891872,"BI":3892601,"RU":3892602}
NEEDS={"SW":[65],"BI":[130,45,150,295],"RU":[100,55,60,40]}
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
  # Read-only live W19 current state for the five approved duration deltas.
  live=await c.get("/plans/v1/plans/685173/workouts/2027-05-10/2027-05-17")
  if live.is_error or not isinstance(live.data,list):return 5
  ids={4001076949,4001076818,4001076854,4001076968,4001076980}
  items=[x for x in live.data if x.get("workoutId") in ids]
  if len(items)!=5 or {x.get("workoutId") for x in items}!=ids:return 6
  print(json.dumps({"stage":"W19_FIVE_NATIVE_SNAPSHOT","plan":685173,"items":[
    {"workout_id":x["workoutId"],"workoutDay":x.get("workoutDay"),
     "sport_id":x.get("workoutTypeValueId"),"title":x.get("title"),
     "description":x.get("description"),"totalTimePlanned":x.get("totalTimePlanned"),
     "structure":x.get("structure")} for x in items]},ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
