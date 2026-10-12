"""Final read-only 24W calendar audit across classic and native Strength surfaces."""
import asyncio,json,httpx
from pathlib import Path
from datetime import date,timedelta
from collections import Counter
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
PLAN=685173
PERSON=6682479
OWNER=2116886
async def main():
 ledger=json.loads(Path("data/chasing_24w_day_ledger_20261012.json").read_text())
 expected=Counter()
 for w in ledger["weeks"]:
  for d,day in enumerate(w["days"]):
   dt=(date(2027,1,4)+timedelta(weeks=w["week"]-1,days=d)).isoformat()
   for kind in ("SW","BI","RU","ST"):
    if day.get(kind):expected[(dt,kind)]+=1
 actual=Counter()
 titles=[]
 async with TPClient() as c:
  u=await c._get_user_data()
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  if u.get("personId")!=OWNER or p.is_error:return 2
  meta=p.data
  if meta.get("planId")!=PLAN or meta.get("planPersonId")!=PERSON or meta.get("isPublic") is not False or meta.get("workoutCount")!=276:return 3
  for startw in range(1,25,4):
   a=(date(2027,1,4)+timedelta(weeks=startw-1)).isoformat()
   b=(date(2027,1,4)+timedelta(weeks=min(startw+3,24))).isoformat()
   r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{a}/{b}")
   if r.is_error or not isinstance(r.data,list):return 4
   for x in r.data:
    day=(x.get("workoutDay") or "")[:10]
    kind={1:"SW",2:"BI",3:"RU"}.get(x.get("workoutTypeValueId"))
    if kind:
     actual[(day,kind)]+=1
     if "test" in (x.get("title") or "").lower() or "benchmark" in (x.get("title") or "").lower():
      titles.append({"date":day,"sport":kind,"title":x.get("title")})
  _,token,err=await _access(c)
  if err:return 5
  native=[]
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   for w in range(1,25):
    a=(date(2027,1,4)+timedelta(weeks=w-1)).isoformat()
    b=(date(2027,1,4)+timedelta(weeks=w)).isoformat()
    r=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/calendar/{PERSON}/{a}/{b}",headers=_headers(token))
    if r.status_code!=200 or not isinstance(r.json(),list):return 6
    for x in r.json():
     dt=(x.get("prescribedDate") or "")[:10]
     actual[(dt,"ST")]+=1
     native.append({"date":dt,"title":x.get("title"),"id":x.get("id")})
 missing=list((expected-actual).elements())
 extra=list((actual-expected).elements())
 print(json.dumps({"stage":"FULL_24W_AUDIT","plan":PLAN,"expected":sum(expected.values()),"observed":sum(actual.values()),"classic":sum(v for (d,k),v in actual.items() if k!="ST"),"native_strength":len(native),"missing":missing[:20],"extra":extra[:20],"duplicate_slots":[[d,k,n] for (d,k),n in actual.items() if n>1],"test_templates":titles,"private":True},ensure_ascii=False),flush=True)
 return 0 if not missing and not extra and sum(actual.values())==276 else 7
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
