"""Read-only compare W01 Chasing and sacrificial Run plan DTO against Run5km library template."""
import asyncio,json
from tp_mcp.client import TPClient
OWNER=2116886
CHASING=685173
LAB=684206
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  if not isinstance(me,dict) or me.get("personId")!=OWNER:return 2
  for plan,a,b in [(LAB,"2027-06-21","2027-06-29"),(CHASING,"2027-01-04","2027-01-11")]:
   p=await c.get(f"/plans/v1/plans/{plan}")
   if p.is_error or p.data.get("isPublic") is not False:return 3
   r=await c.get(f"/plans/v1/plans/{plan}/workouts/{a}/{b}")
   if r.is_error or not isinstance(r.data,list):return 4
   for w in r.data:
    if w.get("workoutTypeValueId") not in (1,2,3):continue
    if plan==LAB and w.get("workoutTypeValueId")!=3:continue
    print(json.dumps({"plan":plan,"id":w.get("workoutId"),"sport":w.get("workoutTypeValueId"),
         "title":w.get("title"),"fields":sorted(w.keys()),
         "typed_fields":{k:{"type":type(w.get(k)).__name__,"value_sample":str(w.get(k))[:130]} for k in (
         "totalTimePlanned","distancePlanned","workoutDay","structure","workoutTypeValueId",
         "workoutSubTypeId","planWorkoutId","title","description") if k in w}},
         ensure_ascii=False),flush=True)
  t=await c.get("/exerciselibrary/v2/libraries/3892602/items")
  if t.is_error:return 5
  test=[v for v in t.data if v.get("exerciseLibraryItemId")==14947461]
  if len(test)!=1:return 6
  print(json.dumps({"library_template_keys":sorted(test[0].keys()),
       "run_template_title":test[0].get("itemName")},ensure_ascii=False),flush=True)
 return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
