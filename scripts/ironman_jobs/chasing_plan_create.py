"""Create a single private, unpriced 24-week CHASING draft plan and seed W01 Tue.
Coach-owned TRAINING PLAN only. No athlete calendar, sale/publication, strength.
Fail closed; never retry an ambiguous POST; read back by exact title/day.
"""
import asyncio, json
from datetime import date, timedelta
from tp_mcp.client import TPClient

OWNER=2116886
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
ANCHOR="2027-01-04"
FIRST="2027-01-05"
LIB=3891872
ITEM=14962927
ITEM_NAME="Tecnica | 2500 m 6x50 + 4x350 facili"
DESCRIPTION=("Bozza privata di produzione CHASING THE SLOT 24 settimane; nuoto/bici/corsa "
 "soltanto. Nessun atleta, nessuna forza finche' non verificata. "
 "I target specifici CSS/ritmo gara richiedono personalizzazione; release commerciale non approvata.")
def log(**kwargs):print(json.dumps(kwargs,ensure_ascii=False),flush=True)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  if not isinstance(me,dict) or me.get("personId")!=OWNER:
   log(stage="OWNER_BLOCK");return 2
  listing=await c.get("/plans/v1/plans")
  if listing.is_error or not isinstance(listing.data,list):
   log(stage="PLAN_LIST_UNAVAILABLE");return 2
  exact=[x for x in listing.data if (x.get("title") or "").strip()==TITLE]
  if len(exact)>1:
   log(stage="TITLE_COLLISION",count=len(exact));return 3
  if exact:
   plan_id=exact[0].get("planId")
   p=await c.get(f"/plans/v1/plans/{plan_id}")
   if p.is_error or not isinstance(p.data,dict):
    log(stage="EXISTING_PLAN_READ_UNAVAILABLE");return 3
   d=p.data
   if d.get("planId")!=plan_id or d.get("isPublic") is not False or d.get("price") not in (None,0):
    log(stage="EXISTING_PLAN_UNSAFE");return 3
   if d.get("workoutCount") not in (None,0,1):
    log(stage="EXISTING_PLAN_NOT_EMPTY",plan_id=plan_id,count=d.get("workoutCount"));return 3
   log(stage="EXISTING_DRAFT_REUSED",plan_id=plan_id,count=d.get("workoutCount"),anchor=d.get("startDate"))
  else:
   payload={"title":TITLE,"startDate":ANCHOR+"T00:00:00",
            "weekCount":24,"dayCount":168,"isPublic":False,"description":DESCRIPTION}
   r=await c._request("POST","/plans/v1/plans",json=payload,_retry_on_401=False)
   if r.is_error:
    log(stage="CREATE_REJECTED_OR_UNCERTAIN_STOP",code=str(r.error_code),retry=False);return 4
   now=await c.get("/plans/v1/plans")
   if now.is_error or not isinstance(now.data,list):
    log(stage="CREATE_UNCERTAIN_LIST_FAILED",retry=False);return 4
   matches=[x for x in now.data if (x.get("title") or "").strip()==TITLE]
   if len(matches)!=1 or not matches[0].get("planId"):
    log(stage="CREATE_UNVERIFIED",matches=len(matches),retry=False);return 4
   plan_id=matches[0]["planId"]
  detail=await c.get(f"/plans/v1/plans/{plan_id}")
  if detail.is_error or not isinstance(detail.data,dict):
   log(stage="DETAIL_UNAVAILABLE",plan_id=plan_id);return 5
  d=detail.data
  if d.get("title")!=TITLE or d.get("planId")!=plan_id or d.get("isPublic") is not False or d.get("price") not in (None,0):
   log(stage="GUARD_PLAN",plan_id=plan_id);return 5
  sd=(d.get("startDate") or "")[:10]
  if sd and sd not in (ANCHOR,FIRST):
   log(stage="BAD_ANCHOR",plan_id=plan_id,start=sd);return 5
  source=await c.get(f"/exerciselibrary/v2/libraries/{LIB}/items")
  if source.is_error or not isinstance(source.data,list):
   log(stage="SOURCE_UNAVAILABLE",plan_id=plan_id);return 5
  item=next((x for x in source.data if x.get("exerciseLibraryItemId")==ITEM),None)
  if not item or item.get("itemName")!=ITEM_NAME or item.get("workoutTypeId")!=1 or item.get("distancePlanned")!=2500:
   log(stage="SOURCE_DRIFT",plan_id=plan_id);return 5
  async def dayread():
   x=await c.get(f"/plans/v1/plans/{plan_id}/workouts/{ANCHOR}/2027-01-07")
   if x.is_error or not isinstance(x.data,list):return None
   return x.data
  before=await dayread()
  if before is None:
   log(stage="PREFLIGHT_PLAN_READ_FAILED",plan_id=plan_id);return 5
  if any(x.get("workoutTypeValueId")==6 for x in before):
   log(stage="STRENGTH_FORBIDDEN",plan_id=plan_id);return 5
  matches=[x for x in before if (x.get("workoutDay") or "")[:10]==FIRST and x.get("title")==ITEM_NAME]
  if len(matches)>1:
   log(stage="DUPLICATE_FIRST_SEED",plan_id=plan_id);return 5
  if not matches:
   if before or d.get("workoutCount") not in (0,None):
    log(stage="NONEMPTY_UNEXPECTED_BEFORE_SEED",plan_id=plan_id,count=d.get("workoutCount"));return 5
   payload={"planId":plan_id,"exerciseLibraryItemId":ITEM,"workoutDateTime":FIRST}
   r=await c._request("POST",f"/plans/v1/plans/{plan_id}/commands/addworkoutfromlibraryitem",
                       json=payload,_retry_on_401=False)
   if r.is_error:
    log(stage="SEED_POST_UNCERTAIN_STOP",plan_id=plan_id,retry=False,code=str(r.error_code));return 6
  after=await dayread()
  if after is None:
   log(stage="SEED_READBACK_UNAVAILABLE",plan_id=plan_id);return 6
  hits=[x for x in after if (x.get("workoutDay") or "")[:10]==FIRST and x.get("title")==ITEM_NAME]
  if len(hits)!=1 or hits[0].get("workoutTypeValueId")!=1 or hits[0].get("description")!=item.get("description"):
   log(stage="SEED_MISMATCH",plan_id=plan_id,matches=len(hits));return 6
  p=await c.get(f"/plans/v1/plans/{plan_id}")
  if p.is_error or not isinstance(p.data,dict) or p.data.get("isPublic") is not False:
   log(stage="POSTFLIGHT_PLAN_UNVERIFIED",plan_id=plan_id);return 6
  log(stage="SEED_VERIFIED",plan_id=plan_id,title=TITLE,
      date=FIRST,library_id=LIB,item_id=ITEM,
      provider_week_count=p.data.get("weekCount"),provider_start=p.data.get("startDate"),
      workout_count=p.data.get("workoutCount"),
      private=True,athletes_modified=0,strength=0)
  return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
