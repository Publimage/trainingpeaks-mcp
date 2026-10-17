"""Guarded native Strength Builder product batch, copied from verified private templates."""
import asyncio,json,copy,uuid,httpx
from datetime import date,timedelta
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE
PLAN=685173
PERSON=6682479
OWNER=2116886
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
START_WEEK=17
END_WEEK=21
EXPECTED_BEFORE=271
TEMPLATES={"A60":"330618","B60":"330621","M60":"330624","D40":"330626","D45":"330626","M45":"330628","M40":"330628","M35":"330629","M30":"330629"}
def log(**v):print(json.dumps(v,ensure_ascii=False),flush=True)
def title(w,d,k):return f"CHASING THE SLOT | W{w:02d} {['LUN','MAR','MER','GIO','VEN','SAB','DOM'][d]} | Forza {k}"
async def main():
 ledger=json.loads(Path("data/chasing_24w_day_ledger_20261012.json").read_text())
 todo=[]
 for week in ledger["weeks"]:
  w=week["week"]
  if START_WEEK<=w<=END_WEEK:
   for d,day in enumerate(week["days"]):
    if day.get("ST"):
     k=day["strength_template"]
     if k not in TEMPLATES:return 2
     todo.append((w,d,k,day["ST"],(date(2027,1,4)+timedelta(weeks=w-1,days=d)).isoformat()))
 if len(todo)!={ (1,8):14,(9,16):8,(17,21):5 }[(START_WEEK,END_WEEK)]:return 3
 async with TPClient() as c:
  u=await c._get_user_data()
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  if u.get("personId")!=OWNER or p.is_error:return 4
  x=p.data
  if x.get("planId")!=PLAN or x.get("planPersonId")!=PERSON or x.get("ownerPersonId")!=OWNER or x.get("title")!=TITLE or x.get("isPublic") is not False or x.get("price") not in (None,0) or x.get("workoutCount")!=EXPECTED_BEFORE or (x.get("startDate") or "")[:10]!="2027-01-05":
   log(stage="STOP_PLAN_SCOPE",count=x.get("workoutCount"));return 5
  _,token,err=await _access(c)
  if err:return 6
  async with httpx.AsyncClient(timeout=25,follow_redirects=False) as h:
   headers=_headers(token)
   lib=await h.get(STRENGTH_API_BASE+"/rx/activity/v1/libraryContent/workoutLibrary/3894341",headers=headers)
   if lib.status_code!=200:return 7
   raw=lib.json();items=raw.get("data",raw) if isinstance(raw,dict) else raw
   sources={str(v.get("id")):v for v in items if isinstance(v,dict)}
   for w,d,k,minutes,dt in todo:
    v=sources.get(TEMPLATES[k])
    if not v or v.get("workoutLibraryItemType")!="ActivityWorkoutTemplate" or (v.get("workout") or {}).get("workoutType")!="StructuredStrength" or len((v.get("workout") or {}).get("blocks") or [])<5:return 8
   existing={}
   for w in range(START_WEEK,END_WEEK+1):
    a=(date(2027,1,4)+timedelta(weeks=w-1)).isoformat()
    b=(date(2027,1,4)+timedelta(weeks=w)).isoformat()
    rr=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/calendar/{PERSON}/{a}/{b}",headers=headers)
    if rr.status_code!=200 or not isinstance(rr.json(),list):return 9
    for v in rr.json():
     key=((v.get("prescribedDate") or "")[:10],v.get("title"))
     if key in existing:return 10
     existing[key]=v
   allowed={(dt,title(w,d,k)) for w,d,k,_,dt in todo}
   if any(key not in allowed for key in existing):
    log(stage="STOP_UNEXPECTED_NATIVE",existing=len(existing));return 11
   if (START_WEEK,END_WEEK)==(1,8) and set(existing)!={( "2027-01-05",title(1,1,"A60"))}:return 12
   if (START_WEEK,END_WEEK)!=(1,8) and existing:return 13
   done=0
   for w,d,k,minutes,dt in todo:
    name=title(w,d,k)
    if (dt,name) in existing:
     if len(existing[(dt,name)].get("blocks") or [])==0:
      check=await h.get(STRENGTH_API_BASE+"/rx/activity/v1/workouts/"+str(existing[(dt,name)].get("id")),headers=headers)
      if check.status_code!=200 or len((check.json().get("data") or {}).get("blocks") or [])<5:return 14
     continue
    source=sources[TEMPLATES[k]]["workout"]
    workout=copy.deepcopy(source)
    workout["id"]=str(uuid.uuid4());workout["calendarId"]=PERSON;workout["prescribedDate"]=dt;workout["title"]=name;workout["prescribedDurationInSeconds"]=minutes*60
    for block in workout["blocks"]:
     block["id"]=str(uuid.uuid4())
     for pres in block.get("prescriptions") or []:
      pres["id"]=str(uuid.uuid4())
      for st in pres.get("sets") or []:
       if "id" in st:st["id"]=str(uuid.uuid4())
    try:res=await h.post(STRENGTH_API_BASE+f"/rx/activity/v1/plans/{PLAN}/workouts/save",json=workout,headers=headers)
    except httpx.RequestError:
     log(stage="AMBIGUOUS_POST",week=w,day=d,inserted=done,retry=False);return 15
    if res.status_code!=200:
     log(stage="PROVIDER_REJECTED",week=w,day=d,http=res.status_code,inserted=done);return 16
    data=res.json().get("data") or {}
    wid=str(data.get("id") or workout["id"])
    check=await h.get(STRENGTH_API_BASE+"/rx/activity/v1/workouts/"+wid,headers=headers)
    pp=await c.get(f"/plans/v1/plans/{PLAN}")
    v=check.json().get("data") if check.status_code==200 else {}
    if not v or v.get("title")!=name or v.get("calendarId")!=PERSON or v.get("workoutType")!="StructuredStrength" or len(v.get("blocks") or [])!=len(source["blocks"]) or pp.is_error or pp.data.get("workoutCount")!=EXPECTED_BEFORE+done+1:
     log(stage="STOP_READBACK",week=w,day=d,inserted=done,retry=False);return 17
    done+=1
   final=await c.get(f"/plans/v1/plans/{PLAN}")
   expected=EXPECTED_BEFORE+len(todo)-len(existing)
   if final.is_error or final.data.get("workoutCount")!=expected:return 18
   log(stage="NATIVE_STRENGTH_BATCH_PASS",weeks=[START_WEEK,END_WEEK],expected=len(todo),inserted=done,already=len(existing),count=expected,private=True,athletes=0)
   return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
