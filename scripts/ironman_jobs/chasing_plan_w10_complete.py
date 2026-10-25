"""Guarded Chasing plan assembly W10 aerobic robustness (SW/BI/RU only).
Incremental scoped QA, no Strength, no athlete calendars; stop on uncertain write.
"""
import asyncio,json
from datetime import date,timedelta
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
BASE=date(2027,1,4)
LIB={"SW":3891872,"BI":3892601,"RU":3892602}
SPORT={"SW":1,"BI":2,"RU":3}
ITEMS=[
 (10,1,"SW",14945195),(10,1,"BI",14963083),
 (10,2,"SW",14945433),(10,2,"RU",14947531),
 (10,3,"BI",14963101),(10,3,"RU",14962916),
 (10,4,"SW",14945597),(10,4,"RU",14962916),
 (10,5,"BI",14963109),(10,6,"RU",14963092),
]
def log(**v):print(json.dumps(v,ensure_ascii=False),flush=True)
def when(w,d):return BASE+timedelta(weeks=w-1,days=d)
async def main():
 async with TPClient() as c:
  user=await c._get_user_data()
  if not isinstance(user,dict) or user.get("personId")!=OWNER:
   log(stage="STOP_OWNER");return 2
  plan=await c.get(f"/plans/v1/plans/{PLAN}")
  if plan.is_error or not isinstance(plan.data,dict):
   log(stage="STOP_PLAN_READ");return 2
  p=plan.data
  if p.get("planId")!=PLAN or p.get("title")!=TITLE or p.get("isPublic") is not False or p.get("price") not in (None,0):
   log(stage="STOP_PLAN_SCOPE");return 2
  if (p.get("startDate") or "")[:10] not in (BASE.isoformat(),(BASE+timedelta(days=1)).isoformat()):
   log(stage="STOP_ANCHOR");return 2
  if len(ITEMS)!=len({(w,d,s) for w,d,s,_ in ITEMS}) or len(ITEMS)!=10 or {w for w,_,_,_ in ITEMS}!={10}:
   log(stage="STOP_MANIFEST");return 3
  source={}
  for kind,lib in LIB.items():
   r=await c.get(f"/exerciselibrary/v2/libraries/{lib}/items")
   if r.is_error or not isinstance(r.data,list):
    log(stage="STOP_SOURCE_READ",kind=kind);return 3
   source[kind]={a.get("exerciseLibraryItemId"):a for a in r.data}
  for w,d,kind,item_id in ITEMS:
   item=source[kind].get(item_id)
   if not item or item.get("workoutTypeId")!=SPORT[kind] or not item.get("description") or not item.get("itemName"):
    log(stage="STOP_SOURCE_DRIFT",item_id=item_id);return 3
  async def read(a,b):
   r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{a}/{b}")
   return None if r.is_error or not isinstance(r.data,list) else r.data
  start=when(10,0).isoformat()
  end=when(11,0).isoformat()
  initial=await read(start,end)
  if initial is None:log(stage="STOP_PREFLIGHT_READ");return 4
  allowed={(when(w,d).isoformat(),SPORT[kind],source[kind][item_id]["itemName"])
           for w,d,kind,item_id in ITEMS}
  for x in initial:
   key=((x.get("workoutDay") or "")[:10],x.get("workoutTypeValueId"),x.get("title"))
   if key not in allowed:
    log(stage="STOP_UNEXPECTED_EXISTING",key=key);return 4
  verified=0;already=0
  for w,d,kind,item_id in ITEMS:
   day=when(w,d).isoformat()
   source_item=source[kind][item_id]
   title=source_item["itemName"]
   sport=SPORT[kind]
   today=await read(day,(when(w,d)+timedelta(days=1)).isoformat())
   if today is None:log(stage="STOP_DAY_PREFLIGHT",day=day);return 5
   other=[x for x in today if (x.get("workoutDay") or "")[:10]==day and x.get("workoutTypeValueId")==sport and x.get("title")!=title]
   if other:
    log(stage="STOP_SPORT_COLLISION",day=day,kind=kind);return 5
   matches=[x for x in today if (x.get("workoutDay") or "")[:10]==day and x.get("title")==title and x.get("workoutTypeValueId")==sport]
   if len(matches)>1:log(stage="STOP_DUPLICATE",day=day,item=item_id);return 5
   if len(matches)==1:
    if matches[0].get("description")!=source_item.get("description"):
     log(stage="STOP_EXISTING_MISMATCH",day=day,item=item_id);return 5
    already+=1
    continue
   r=await c._request("POST",f"/plans/v1/plans/{PLAN}/commands/addworkoutfromlibraryitem",
                      json={"planId":PLAN,"exerciseLibraryItemId":item_id,"workoutDateTime":day},
                      _retry_on_401=False)
   if r.is_error:
    log(stage="STOP_AMBIGUOUS_WRITE",day=day,item=item_id,verified=verified,retry=False);return 6
   after=await read(day,(when(w,d)+timedelta(days=1)).isoformat())
   if after is None:
    log(stage="STOP_READBACK_UNAVAILABLE",day=day,item=item_id,verified=verified,retry=False);return 6
   good=[x for x in after if (x.get("workoutDay") or "")[:10]==day and x.get("title")==title and x.get("workoutTypeValueId")==sport and x.get("description")==source_item.get("description")]
   if len(good)!=1:
    log(stage="STOP_READBACK_MISMATCH",day=day,item=item_id,verified=verified);return 6
   verified+=1
  latest=await read(start,end)
  if latest is None:log(stage="STOP_FINAL_READ");return 7
  found=[x for x in latest if when(10,0).isoformat()<=(x.get("workoutDay") or "")[:10]<when(11,0).isoformat()]
  actual={((x.get("workoutDay") or "")[:10],x.get("workoutTypeValueId"),x.get("title")) for x in found}
  if len(found)!=len(ITEMS) or actual!=allowed:
   log(stage="STOP_FINAL_SET",got=len(found),expect=len(ITEMS));return 7
  log(stage="W10_ENDURANCE_PASS",plan=PLAN,expected=len(ITEMS),observed=len(found),
      inserted=verified,already_verified=already,private=True,strength=0,athletes=0)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
