"""Remove only trailing CODICE WORKOUT blocks from private CHASING plan copies.
Keep a local audit backup of original native provider DTOs and code->provider-ID mapping.
No writes to Workout Library or athlete calendars. Transport dates are API only.
"""
import asyncio
import json
import re
import hashlib
from pathlib import Path
from tp_mcp.client import TPClient
PLAN=685173
OWNER=2116886
PERSON=6682479
RANGES=(("2027-01-04","2027-02-28"),("2027-03-01","2027-04-25"),("2027-04-26","2027-06-20"))
CODE=re.compile(r"\n{1,3}CODICE WORKOUT\s*\n([A-Z0-9-]+)\s*$",re.I)
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_685173_code_cleanup_20261014_backup.json"
def must(a,b):
 if not a:raise RuntimeError(b)
def stable(x):return {k:v for k,v in x.items() if k!="lastModifiedDate"}
def hashit(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
async def fetch(c):
 out=[];notes=[]
 for a,b in RANGES:
  r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{a}/{b}")
  n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{a}/{b}")
  must(not r.is_error and not n.is_error and isinstance(r.data,list) and isinstance(n.data,list),"NATIVE_READ_FAILED")
  out+=r.data;notes.append(n.data)
 must(len(out)==249 and len(set(w["workoutId"] for w in out))==249,"PLAN_249_COUNT_DRIFT")
 return out,hashit(notes)
async def readone(c,index):
 a,b=RANGES[index]
 r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{a}/{b}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{a}/{b}")
 must(not r.is_error and not n.is_error,"BLOCK_READ_FAILED")
 return r.data,hashit(n.data)
async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  must(u.get("personId")==OWNER,"OWNER_MISMATCH")
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  must(not p.is_error and p.data.get("planId")==PLAN and p.data.get("planPersonId")==PERSON and p.data.get("isPublic") is False and p.data.get("workoutCount")==276 and "BOZZA" in (p.data.get("title") or ""),"PLAN_NOT_PRIVATE_DRAFT")
  rows,notes=await fetch(c)
  patches={};mapping=[]
  for w in rows:
   d=w.get("description") or ""
   m=CODE.search(d)
   if not m:continue
   q=dict(w)
   q["description"]=d[:m.start()]
   must(q["description"] and q["description"] not in (d,),"DESCRIPTION_NOT_CHANGED")
   must(CODE.search(q["description"]) is None,"CODE_STILL_PRESENT")
   must(all(q[k]==w[k] for k in w if k!="description"),"UNEXPECTED_PAYLOAD_DRIFT")
   patches[w["workoutId"]]=q
   mapping.append({"id":w["workoutId"],"code":m.group(1),"title":w.get("title"),"workoutDay":w.get("workoutDay"),"sport":w.get("workoutTypeValueId")})
 must(len(patches)==172,"CODE_COUNT_EXPECTED_172_BUT_"+str(len(patches)))
 must(not BACKUP.exists(),"BACKUP_ALREADY_EXISTS_RECONCILE")
 BACKUP.parent.mkdir(parents=True,exist_ok=True)
 BACKUP.write_text(json.dumps({"plan":PLAN,"original":rows,"note_hash":notes,"mapping":mapping},ensure_ascii=False,indent=2)+"\n")
 expected={w["workoutId"]:stable(w) for w in rows}
 print(json.dumps({"stage":"PREFLIGHT_PASS","target":len(patches),"backup":str(BACKUP)}),flush=True)
 for n,(wid,body) in enumerate(patches.items()):
  original=expected[wid]
  idx=next(i for i,(a,b) in enumerate(RANGES) if a<=str(body["workoutDay"])[:10]<=b)
  current,nh=await readone(c,idx)
  now={w["workoutId"]:w for w in current}
  must(isinstance(nh,str) and len(nh)==64,"NOTES_READ_FAILED")
  must(stable(now[wid])==original,"PREWRITE_DRIFT_"+str(wid))
  result=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",json=body,_retry_on_401=False)
  after,an=await readone(c,idx)
  am={w["workoutId"]:w for w in after}
  must(not result.is_error and stable(am[wid])==stable(body),"UNVERIFIED_WRITE_"+str(wid))
  expected[wid]=stable(body)
  must(all(stable(am[k])==expected[k] for k in am),"UNRELATED_WORKOUT_CHANGED_"+str(wid))
  if (n+1)%10==0:print(json.dumps({"stage":"VERIFIED_PROGRESS","done":n+1}),flush=True)
 final,fnotes=await fetch(c)
 must(fnotes==notes and all(stable(w)==expected[w["workoutId"]] for w in final),"FINAL_NOT_EXACT")
 must(all(not CODE.search(w.get("description") or "") for w in final),"CODE_REMAINING")
 print(json.dumps({"stage":"PASS_ALL_172","cleaned":172,"workouts":249,"preserved":True,"plan_private":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","error":str(e)[:500]}),flush=True)
  raise
