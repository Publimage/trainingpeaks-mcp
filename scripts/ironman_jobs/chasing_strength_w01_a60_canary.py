"""One guarded native Strength A60 W01 product canary, after lab proof."""
import asyncio,json,copy,uuid,httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
PLAN=685173
OWNER=2116886
PERSON=6682479
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
NEW="CHASING THE SLOT | W01 MAR | Forza A60"
DATE="2027-01-05"
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  r=await c.get(f"/plans/v1/plans/{PLAN}")
  if u.get("personId")!=OWNER or r.is_error:return 2
  p=r.data
  if p.get("planId")!=PLAN or p.get("planPersonId")!=PERSON or p.get("ownerPersonId")!=OWNER or p.get("title")!=TITLE or p.get("isPublic") is not False or p.get("price") not in (None,0) or p.get("workoutCount")!=249 or (p.get("startDate") or "")[:10]!="2027-01-05":
   print('{"stage":"STOP_SCOPE"}',flush=True);return 3
  _,token,err=await _access(c)
  if err:return 4
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   headers=_headers(token)
   before=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/calendar/{PERSON}/2027-01-04/2027-01-07",headers=headers)
   if before.status_code!=200 or not isinstance(before.json(),list) or before.json():
    print('{"stage":"STOP_EXISTING_NATIVE"}',flush=True);return 5
   lib=await h.get(STRENGTH_API_BASE+"/rx/activity/v1/libraryContent/workoutLibrary/3894341",headers=headers)
   if lib.status_code!=200:return 6
   raw=lib.json();items=raw.get("data",raw) if isinstance(raw,dict) else raw
   matches=[x for x in items if str(x.get("id"))=="330618"]
   if len(matches)!=1 or matches[0].get("title")!="CHASING THE SLOT | Forza A60 | Adattamento full body + WarmUp":return 7
   w=copy.deepcopy(matches[0].get("workout") or {})
   if w.get("workoutType")!="StructuredStrength" or len(w.get("blocks") or [])!=9:return 8
   w["id"]=str(uuid.uuid4());w["calendarId"]=PERSON;w["prescribedDate"]=DATE;w["title"]=NEW;w["prescribedDurationInSeconds"]=3600
   for b in w["blocks"]:
    b["id"]=str(uuid.uuid4())
    for pres in b.get("prescriptions") or []:
     pres["id"]=str(uuid.uuid4())
     for st in pres.get("sets") or []:
      if "id" in st:st["id"]=str(uuid.uuid4())
   print(json.dumps({"stage":"PREFLIGHT","plan":PLAN,"date":DATE,"blocks":9,"expected_count":249}),flush=True)
   try:response=await h.post(STRENGTH_API_BASE+f"/rx/activity/v1/plans/{PLAN}/workouts/save",json=w,headers=headers)
   except httpx.RequestError:
    print('{"stage":"AMBIGUOUS_POST","retry":false}',flush=True);return 9
   if response.status_code!=200:
    print(json.dumps({"stage":"PROVIDER_REJECTED","http":response.status_code}),flush=True);return 10
   d=response.json().get("data") or {}
   wid=str(d.get("id") or w["id"])
   check=await h.get(STRENGTH_API_BASE+"/rx/activity/v1/workouts/"+wid,headers=headers)
   pp=await c.get(f"/plans/v1/plans/{PLAN}")
   found=check.json().get("data") or {} if check.status_code==200 else {}
   ok=bool(found.get("title")==NEW and found.get("calendarId")==PERSON and found.get("workoutType")=="StructuredStrength" and len(found.get("blocks") or [])==9 and not pp.is_error and pp.data.get("workoutCount")==250)
   print(json.dumps({"stage":"NATIVE_CANARY","ok":ok,"id":wid,"plan_count":pp.data.get("workoutCount") if not pp.is_error else None,"blocks":len(found.get("blocks") or [])}),flush=True)
   return 0 if ok else 11
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
