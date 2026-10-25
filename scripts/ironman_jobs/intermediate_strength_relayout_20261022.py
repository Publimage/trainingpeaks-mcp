"""Guarded in-place relocation of approved Intermediate native StructuredStrength workouts.
Exact 22 workout ids; preserve structure and duration. No athlete or library writes.
"""
from __future__ import annotations
import asyncio, copy, hashlib, json, httpx
from datetime import date,timedelta
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE

PLAN=684602
PERSON=6678583
OWNER=2116886
TITLE="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
BASE=date(2026,10,5)
END=(BASE+timedelta(weeks=24,days=2)).isoformat()
DAYS=("MON","TUE","WED","THU","FRI","SAT","SUN")
# id, week, expected original weekday, approved target weekday (0=MON)
MOVES=[
 (33973536,1,4,0),(33973541,2,4,0),(33973547,3,4,0),
 (33973559,5,4,0),(33973567,6,4,0),(33973576,7,4,0),
 (33973578,8,2,5),
 (33973581,9,1,2),(33973582,9,4,0),
 (33973585,10,1,2),(33973587,10,4,0),
 (33973589,11,1,2),(33973592,12,1,2),(33973598,13,1,2),
 (33973600,14,1,2),(33973605,15,1,2),
 (33973614,17,1,2),(33973619,18,1,2),(33973624,19,1,2),
 (33973629,20,1,2),(33973632,21,1,2),(33973634,22,1,2)
]
CANARY_ID=33973536

def must(check,label):
 if not check:raise RuntimeError(label)
def when(week,day):
 return (BASE+timedelta(weeks=week-1,days=day)).isoformat()
def sha(x):
 return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
async def run(canary=False):
 selected=[x for x in MOVES if (x[0]==CANARY_ID)==canary]
 must(len(MOVES)==22 and len({x[0] for x in MOVES})==22,"MOVES_SCOPE")
 must(len(selected)==(1 if canary else 21),"MODE_SCOPE")
 async with TPClient() as c:
  me=await c._get_user_data()
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  must(isinstance(me,dict) and me.get("personId")==OWNER and not p.is_error,"OWNER_OR_PLAN")
  meta=p.data
  must(meta.get("planId")==PLAN and meta.get("planPersonId")==PERSON and
       meta.get("ownerPersonId")==OWNER and meta.get("title")==TITLE and
       meta.get("isPublic") is True and meta.get("workoutCount")==259 and
       meta.get("weekCount")==24 and str(meta.get("startDate"))[:10]==BASE.isoformat(),
       "INTERMEDIATE_PLAN_SCOPE")
  _,token,err=await _access(c)
  must(not err and token,"STRENGTH_AUTH")
  headers=_headers(token)
  async with httpx.AsyncClient(timeout=35,follow_redirects=False) as h:
   async def list_native():
    r=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/plans/{PLAN}/workouts/{BASE.isoformat()}/{END}",headers=headers)
    must(r.status_code==200,f"NATIVE_PLAN_READ_{r.status_code}")
    obj=r.json()
    rows=obj.get("data") if isinstance(obj,dict) else obj
    must(isinstance(rows,list) and len(rows)==30,"NATIVE_COUNT")
    must(len({str(x.get("id") or x.get("workoutId")) for x in rows})==30,"DUPLICATE_NATIVE_IDS")
    return rows
   async def detail(wid):
    r=await h.get(STRENGTH_API_BASE+f"/rx/activity/v1/workouts/{wid}",headers=headers)
    must(r.status_code==200,f"NATIVE_DETAIL_{wid}_{r.status_code}")
    d=r.json()
    v=d.get("data") if isinstance(d,dict) else d
    must(isinstance(v,dict) and str(v.get("id"))==str(wid),"NATIVE_DETAIL_SHAPE")
    return v
   existing=await list_native()
   index={str(x.get("id") or x.get("workoutId")):x for x in existing}
   targets=[];already=[]
   for wid,w,old_day,new_day in selected:
    target_key=str(wid)
    must(target_key in index,"MISSING_ID_"+target_key)
    original=await detail(wid)
    old_date=when(w,old_day)
    new_date=when(w,new_day)
    old_marker=f"W{w:02d} {DAYS[old_day]}"
    new_marker=f"W{w:02d} {DAYS[new_day]}"
    title=original.get("title") or ""
    must(original.get("calendarId")==PERSON and original.get("workoutType")=="StructuredStrength"
         and len(original.get("blocks") or [])>=4 and
         original.get("prescribedDurationInSeconds",0)>0,
         "NATIVE_SCOPE_"+target_key)
    if str(original.get("prescribedDate"))[:10]==new_date and new_marker in title:
     already.append(target_key)
     continue
    must(str(original.get("prescribedDate"))[:10]==old_date and title.count(old_marker)==1,
         "SOURCE_DRIFT_"+target_key)
    must(not any(str(x.get("prescribedDate"))[:10]==new_date for x in existing),
         "DEST_NOT_EMPTY_"+target_key)
    updated=title.replace(old_marker,new_marker)
    targets.append({"id":wid,"week":w,"from":old_date,"to":new_date,
                    "title_before":title,"title_after":updated,
                    "block_sha":sha(original["blocks"]),
                    "duration":original["prescribedDurationInSeconds"],
                    "raw":original})
   journal=Path.home()/".trainingpeaks-mcp"/("intermediate_strength_move_canary_20261022.json" if canary else "intermediate_strength_move_rest_20261022.json")
   if targets:
    must(not journal.exists(),"PREVIOUS_WRITE_JOURNAL_EXISTS_STOP")
    journal.parent.mkdir(parents=True,exist_ok=True)
    journal.write_text(json.dumps({"plan":PLAN,"mode":"canary" if canary else "remaining","targets":targets},
                                  ensure_ascii=False,default=str)+"\n",encoding="utf-8")
   print(json.dumps({"stage":"INTERMEDIATE_NATIVE_MOVE_PREFLIGHT","mode":"canary" if canary else "remaining",
      "selected":len(selected),"to_move":len(targets),"already":len(already),
      "workout_count":259,"native_count":30,"provider_writes":0}),flush=True)
   for idx,t in enumerate(targets):
    current=await detail(t["id"])
    must(current.get("title")==t["title_before"] and
         str(current.get("prescribedDate"))[:10]==t["from"] and
         sha(current.get("blocks"))==t["block_sha"] and
         current.get("prescribedDurationInSeconds")==t["duration"],
         "MID_BATCH_DRIFT_"+str(t["id"]))
    payload=copy.deepcopy(current)
    payload["title"]=t["title_after"]
    payload["prescribedDate"]=t["to"]
    status=None
    try:
     res=await h.post(STRENGTH_API_BASE+f"/rx/activity/v1/plans/{PLAN}/workouts/save",headers=headers,json=payload)
     status=res.status_code
    except httpx.RequestError:
     pass
    final=await detail(t["id"])
    must(status==200 and final.get("title")==t["title_after"] and
         str(final.get("prescribedDate"))[:10]==t["to"] and
         final.get("calendarId")==PERSON and
         sha(final.get("blocks"))==t["block_sha"] and
         final.get("prescribedDurationInSeconds")==t["duration"],
         "NATIVE_WRITE_AMBIGUOUS_STOP_"+str(t["id"]))
    check=await c.get(f"/plans/v1/plans/{PLAN}")
    must(not check.is_error and check.data.get("workoutCount")==259 and
         check.data.get("isPublic") is True,"PLAN_DRIFT_POST_MOVE")
    print(json.dumps({"stage":"INTERMEDIATE_NATIVE_MOVE_VERIFIED","id":t["id"],"week":t["week"],
      "from":t["from"],"to":t["to"],"step":idx+1}),flush=True)
   after=await list_native()
   final_index={str(x.get("id") or x.get("workoutId")):x for x in after}
   for wid,w,old_day,new_day in selected:
    v=final_index[str(wid)]
    must(str(v.get("prescribedDate"))[:10]==when(w,new_day) and
         f"W{w:02d} {DAYS[new_day]}" in str(v.get("title")),
         "POSTFLIGHT_MISSING_"+str(wid))
   print(json.dumps({"stage":"INTERMEDIATE_NATIVE_STRENGTH_RELAYOUT_VERIFIED",
      "mode":"canary" if canary else "remaining","moved":len(targets),"already":len(already),
      "native_total":len(after),"total_plan_workouts":259,
      "athlete_calendar_writes":0,"library_writes":0}),flush=True)
   return 0
