"""Add exactly W01-W02 swim/bike/run to existing private CHASING plan.
In-place plan only, source common IT libraries. Never athlete/strength.
Each add is idempotency-guarded, followed by exact-date readback;
ambiguous writes STOP without blind retry. Known calendar starts Tuesday.
"""
import asyncio,json
from datetime import date,timedelta
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
ANCHOR=date(2027,1,4)
LIB={"SW":3891872,"BI":3892601,"RU":3892602}
ITEMS=[
 (1,1,"SW",14962927),(1,1,"BI",14962510),
 (1,2,"SW",14962929),(1,2,"RU",14962554),
 (1,3,"BI",14962511),(1,3,"RU",14962915),
 (1,4,"SW",14962930),(1,4,"RU",14962916),
 (1,5,"BI",14962920),(1,6,"RU",14962919),
 (2,1,"SW",14962936),(2,1,"BI",14962985),
 (2,2,"SW",14962929),(2,2,"RU",14962999),
 (2,3,"BI",14962986),(2,3,"RU",14962915),
 (2,4,"SW",14962937),(2,4,"RU",14963001),
 (2,5,"BI",14962987),(2,6,"RU",14962915),
]
def log(**x):print(json.dumps(x,ensure_ascii=False),flush=True)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  if not isinstance(me,dict) or me.get("personId")!=OWNER:log(stage="STOP_OWNER");return 2
  pr=await c.get(f"/plans/v1/plans/{PLAN}")
  if pr.is_error:log(stage="STOP_PLAN_READ");return 2
  p=pr.data
  if p.get("planId")!=PLAN or p.get("title")!=TITLE or p.get("isPublic") is not False or p.get("price") not in (None,0):
   log(stage="STOP_PLAN_SCOPE");return 2
  if (p.get("startDate") or "")[:10] not in (ANCHOR.isoformat(),(ANCHOR+timedelta(days=1)).isoformat()):
   log(stage="STOP_ANCHOR");return 2
  sources={}
  for key,lid in LIB.items():
   r=await c.get(f"/exerciselibrary/v2/libraries/{lid}/items")
   if r.is_error or not isinstance(r.data,list):log(stage="STOP_LIBRARY",sport=key);return 2
   sources[key]={v.get("exerciseLibraryItemId"):v for v in r.data}
  for w,d,s,id in ITEMS:
   if id not in sources[s] or sources[s][id].get("workoutTypeId")!={"SW":1,"BI":2,"RU":3}[s]:
    log(stage="STOP_TEMPLATE",item=id);return 3
  if len({(w,d,s) for w,d,s,id in ITEMS})!=len(ITEMS):log(stage="STOP_MANIFEST_DUPLICATE");return 3
  async def allread():
   r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/2027-01-04/2027-01-19")
   if r.is_error or not isinstance(r.data,list):return None
   return r.data
  before=await allread()
  if before is None:log(stage="STOP_CALENDAR_READ");return 3
  allowed={(ANCHOR+timedelta(weeks=w-1,days=d)).isoformat():None for w,d,s,id in ITEMS}
  for x in before:
   day=(x.get("workoutDay") or "")[:10]
   if day not in allowed or x.get("workoutTypeValueId") not in (1,2,3):
    log(stage="STOP_UNEXPECTED_EXISTING",date=day,title=x.get("title"));return 3
  written=0;skipped=0
  for w,d,s,id in ITEMS:
   target=(ANCHOR+timedelta(weeks=w-1,days=d)).isoformat()
   src=sources[s][id];title=src["itemName"]
   now=await allread()
   if now is None:log(stage="STOP_READBACK",written=written);return 4
   same=[x for x in now if (x.get("workoutDay") or "")[:10]==target and x.get("title")==title]
   if len(same)>1:log(stage="STOP_DUPLICATE",target=target,code=id);return 4
   if len(same)==1:
    if same[0].get("description")!=src.get("description"):
     log(stage="STOP_EXISTING_MISMATCH",target=target,item=id);return 4
    skipped+=1;continue
   r=await c._request("POST",f"/plans/v1/plans/{PLAN}/commands/addworkoutfromlibraryitem",
                      json={"planId":PLAN,"exerciseLibraryItemId":id,"workoutDateTime":target},_retry_on_401=False)
   if r.is_error:
    log(stage="STOP_AMBIGUOUS_WRITE",target=target,item=id,written=written,retry=False);return 5
   after=await allread()
   if after is None:
    log(stage="STOP_UNVERIFIED_WRITE",target=target,item=id,written=written,retry=False);return 5
   hit=[x for x in after if (x.get("workoutDay") or "")[:10]==target and x.get("title")==title]
   if len(hit)!=1 or hit[0].get("description")!=src.get("description") or hit[0].get("workoutTypeValueId")!={"SW":1,"BI":2,"RU":3}[s]:
    log(stage="STOP_QA_FAIL",target=target,item=id,written=written);return 5
   written+=1
  end=await allread()
  if end is None:log(stage="STOP_FINAL_READ");return 6
  expected=len(ITEMS)
  if len(end)!=expected or any(x.get("workoutTypeValueId") not in (1,2,3) for x in end):
   log(stage="STOP_FINAL_COUNT",actual=len(end),expected=expected);return 6
  log(stage="W01_W02_PASS",plan=PLAN,expected=expected,observed=len(end),
      written=written,already_exact=skipped,
      days=sorted({(x.get("workoutDay") or "")[:10] for x in end}),
      no_strength=True,no_athletes=True)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
