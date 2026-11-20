"""CHASING W01: move existing easy run Fri Jan08 -> Mon Jan04.
Pre-start move reanchors private plan from Jan05 to Jan04 (disposable lab proved);
preserve all instances, intensity, long Saturdays, notes and unmodified dates.
"""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
PERSON=6682479
PLAN=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
SRC="2027-01-08"
DST="2027-01-04"
A="2027-01-04"
B="2027-01-31"
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w01_plan_reanchor_backup.json"
def must(v,s):
 if not v:raise RuntimeError(s)
def wd(x):return str(x.get("workoutDay") or "")[:10]
def uid(x):
 ids=[x[k] for k in ("workoutId","planWorkoutId","id") if type(x.get(k)) is int and x[k]>0]
 must(bool(ids) and len(set(ids))==1,"AMBIGUOUS_ID")
 return ids[0]
def stable(x):return {k:v for k,v in x.items() if k not in ("workoutDay","lastModifiedDate")}
def sha(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
async def read(c,expected_start):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_GET_FAILED")
 v=p.data
 must(v.get("planId")==PLAN and v.get("planPersonId")==PERSON and
      v.get("title")==TITLE and v.get("isPublic") is False and v.get("price") in (None,0)
      and v.get("workoutCount")==276 and str(v.get("startDate") or "")[:10]==expected_start,
      "PLAN_SCOPE_OR_ANCHOR_CHANGED")
 r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{A}/{B}")
 must(not r.is_error and isinstance(r.data,list) and len(r.data)==39,"FIRST_FOUR_WEEKS_COUNT_CHANGED")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{A}/{B}")
 must(not n.is_error and isinstance(n.data,list),"NOTES_GET_FAILED")
 return r.data,sha(n.data)
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  must(me.get("personId")==OWNER,"WRONG_COACH")
  before,notes=await read(c,"2027-01-05")
  src=[v for v in before if wd(v)==SRC and v.get("workoutTypeValueId")==3]
  dst=[v for v in before if wd(v)==DST and v.get("workoutTypeValueId")==3]
  must(len(src)==1 and not dst and "40'" in str(src[0].get("title")),"UNEXPECTED_W01_RUN_OR_TARGET")
  original=src[0]
  before_ids=sorted(uid(v) for v in before)
  must(not BACKUP.exists(),"BACKUP_ALREADY_EXISTS_NO_RETRY")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":PLAN,"original":original,"expected_ids":before_ids,"notes_sha":notes},ensure_ascii=False,indent=2)+"\n")
  payload=dict(original);payload["workoutDay"]=DST+str(original["workoutDay"])[10:]
  print(json.dumps({"stage":"PREFLIGHT","id":uid(original),"source":SRC,"target":DST,"expected_anchor":"2027-01-04"}),flush=True)
  resp=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{uid(original)}",json=payload,_retry_on_401=False)
  after,notes2=await read(c,"2027-01-04")
  hit=[v for v in after if uid(v)==uid(original)]
  must(not resp.is_error and len(hit)==1 and wd(hit[0])==DST,"REANCHOR_UNVERIFIED_NO_RETRY")
  must(stable(hit[0])==stable(original),"MOVED_CONTENT_CHANGED")
  must(sorted(uid(v) for v in after)==before_ids and notes2==notes,"PLAN_CONTENT_OR_NOTES_CHANGED")
  expected_days={uid(v):(DST if uid(v)==uid(original) else wd(v)) for v in before}
  must(all(wd(v)==expected_days[uid(v)] for v in after),"OTHER_WORKOUT_DATES_CHANGED")
  print(json.dumps({"stage":"PASS_REANCHOR_W01","plan":PLAN,"startDate":"2027-01-04",
   "moved_id":uid(original),"workouts":276,"week1_4_classic":39,
   "all_other_dates_unchanged":True,"all_workout_content_preserved":True,
   "notes_preserved":True,"private":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP","reason":str(e)[:230],"no_blind_retry":True}),flush=True)
  raise
