"""Repair 35 verified broken/incomplete CHASING Builder instances from native reusable templates."""
import asyncio,json,hashlib
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
OWNER=2116886;PERSON=6682479;P=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
RANGES=[("2027-01-04","2027-02-28"),("2027-03-01","2027-04-25"),("2027-04-26","2027-06-20")]
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_native_builder_35_repairs_20261013_backup.json"
# Existing exact plan IDs -> existing NEW reusable native template (Library-first, no shared source mutation).
TEMPLATES=[
 (3892602,14976570,[4000973064]),
 (3892602,14976573,[4001048527,4001062302]),
 (3892601,14976575,[4001050288]),
 (3892601,14976579,[4001052997]),
 (3892601,14976581,[4001053067]),
 (3892602,14976583,[4001053081,4001065444,4001072135,4001081245]),
 (3892601,14976585,[4001058948,4001062077,4001071953]),
 (3892601,14976586,[4001059087]),
 (3892601,14976588,[4001059223]),
 (3892602,14976589,[4001059264]),
 (3892601,14976590,[4001062176,4001074506]),
 (3892601,14976591,[4001062280]),
 (3892601,14976592,[4001065348]),
 (3892601,14976594,[4001065433]),
 (3892601,14976595,[4001072016]),
 (3892601,14976596,[4001072083]),
 (3892601,14976597,[4001074463,4001083455]),
 (3892601,14976598,[4001076774]),
 (3892601,14976600,[4001076867]),
 (3892601,14976601,[4001076968]),
 (3892601,14976603,[4001080961]),
 (3892601,14976604,[4001083740]),
 (3892601,14976605,[4001086537]),
 (3892601,14976563,[4001089879]),
 (3892601,14976606,[4001089913]),
 (3891872,14963214,[4001089818,4001089870])]
def must(q,msg):
 if not q:raise RuntimeError(msg)
def digest(o):return hashlib.sha256(json.dumps(o,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def stable(w):return {k:v for k,v in w.items() if k not in ("lastModifiedDate",)}
def day(w):return str(w.get("workoutDay") or "")[:10]
def week(w):return (date.fromisoformat(day(w))-date(2027,1,4)).days//7+1
def targets_absent(w):
 s=w.get("structure")
 if not isinstance(s,dict) or not isinstance(s.get("structure"),list) or not s["structure"]:return True
 return any(v.get("intensityClass")=="active" and not v.get("targets")
   for group in s["structure"] for v in group.get("steps") or [])
async def readall(c):
 rows=[]; notes=[]
 for start,end in RANGES:
  a=await c.get(f"/plans/v1/plans/{P}/workouts/{start}/{end}")
  n=await c.get(f"/plans/v1/plans/{P}/calendarNote/{start}/{end}")
  must(not a.is_error and not n.is_error and isinstance(a.data,list) and isinstance(n.data,list),"READ_FAILED")
  rows.extend(a.data);notes.append(n.data)
 must(len(rows)==249 and len(set(z["workoutId"] for z in rows))==249,"COUNT_249_DRIFT")
 return rows,digest(notes)
async def readblock(c,w):
 start,end=RANGES[min((w-1)//8,2)]
 a=await c.get(f"/plans/v1/plans/{P}/workouts/{start}/{end}")
 n=await c.get(f"/plans/v1/plans/{P}/calendarNote/{start}/{end}")
 expected=(79,82,88)[min((w-1)//8,2)]
 must(not a.is_error and not n.is_error and len(a.data)==expected,"BLOCK_READ_FAILED")
 return a.data,n.data
async def main():
 async with TPClient() as c:
  user=await c._get_user_data()
  must(user.get("personId")==OWNER,"OWNER_MISMATCH")
  r=await c.get(f"/plans/v1/plans/{P}")
  h=r.data
  must(not r.is_error and h.get("planId")==P and h.get("planPersonId")==PERSON and
   h.get("isPublic") is False and h.get("price") in (None,0) and
   h.get("title")==TITLE and h.get("workoutCount")==276,"PRIVATE_PLAN_SCOPE")
  originals,notehash=await readall(c)
  byid={z["workoutId"]:z for z in originals}
  affected={id for _,_,ids in TEMPLATES for id in ids}
  must(len(affected)==35,"AFFECTED_COUNT_NOT_35")
  broken={z["workoutId"] for z in originals if targets_absent(z)}
  must(affected==broken,f"BROKEN_SET_CHANGED missing={sorted(broken-affected)} extra={sorted(affected-broken)}")
  libs={}
  for lid in (3891872,3892601,3892602):
   v=await c.get(f"/exerciselibrary/v2/libraries/{lid}/items")
   must(not v.is_error and isinstance(v.data,list),"LIBRARY_UNREADABLE")
   libs[lid]={x.get("exerciseLibraryItemId"):x for x in v.data}
  patches={}
  for lid,tid,ids in TEMPLATES:
   t=libs[lid].get(tid)
   must(t is not None and isinstance(t.get("structure"),dict) and t["itemName"].count("|")==1
     and "CHASING" not in t["itemName"] and not any(("W"+str(k)) in t["itemName"] for k in range(1,25)),
     "NATIVE_TEMPLATE_OR_TITLE_INVALID_"+str(tid))
   s=t["structure"]
   must(isinstance(s.get("polyline"),list) and len(s["polyline"])>0 and
     len(s.get("structure") or [])>0 and not any(v.get("intensityClass")=="active" and not v.get("targets")
     for group in s["structure"] for v in group.get("steps") or []),
     "TEMPLATE_BUILDER_INCOMPLETE_"+str(tid))
   for wid in ids:
    o=byid[wid]
    must(o.get("workoutTypeValueId")==(1 if lid==3891872 else 2 if lid==3892601 else 3) and
       abs((o.get("totalTimePlanned") or 0)-(t.get("totalTimePlanned") or 0))<0.0001,"SPORT_OR_DURATION_DRIFT_"+str(wid))
    if lid==3891872:
      must(o.get("structure") is None and o.get("distancePlanned")==t.get("distancePlanned")==1200
        and week(o)==24,"SWIM_MISSING_EXPECTED_"+str(wid))
    else:
      must(isinstance(o.get("structure"),dict) and targets_absent(o),"SOURCE_TARGET_EXPECTED_"+str(wid))
    q=dict(o)
    for k,z in (("title","itemName"),("description","description"),
       ("totalTimePlanned","totalTimePlanned"),("distancePlanned","distancePlanned"),
       ("structure","structure"),("workoutSubTypeId","workoutSubTypeId")):q[k]=t.get(z)
    patches[wid]=q
  must(len(patches)==35,"PATCH_COUNT")
  must(not BACKUP.exists(),"BACKUP_EXISTS_RECONCILE_FIRST")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"plan":P,"source":originals,"notehash":notehash,
    "affected_ids":sorted(patches)},ensure_ascii=False,indent=2)+"\n")
  weekly_before={w:round(sum((z.get("totalTimePlanned") or 0)*60 for z in originals if week(z)==w)) for w in range(1,25)}
  expected={i:stable(z) for i,z in byid.items()}
  print(json.dumps({"stage":"PREFLIGHT_PASS","workouts":249,"patched":35,
    "empty_target_instances":33,"missing_swim_builder":2,"private":True}),flush=True)
  block_note_hash={}
  for wid,payload in sorted(patches.items(),key=lambda kv: (week(byid[kv[0]]),day(byid[kv[0]]),kv[0])):
   wk=week(byid[wid]); idx=(wk-1)//8
   before,notes=await readblock(c,wk)
   local={z["workoutId"]:z for z in before}
   if idx not in block_note_hash:block_note_hash[idx]=digest(notes)
   must(digest(notes)==block_note_hash[idx] and stable(local[wid])==expected[wid],
        "PREWRITE_DRIFT_"+str(wid))
   result=await c._request("PUT",f"/plans/v1/plans/{P}/workouts/{wid}",json=payload,_retry_on_401=False)
   after,anotes=await readblock(c,wk);now={z["workoutId"]:z for z in after}
   must(not result.is_error and digest(anotes)==block_note_hash[idx] and stable(now[wid])==stable(payload),
     "WRITE_UNVERIFIED_STOP_"+str(wid))
   expected[wid]=stable(payload)
   must(all(stable(now[i])==expected[i] for i in now),"OTHER_ITEM_CHANGED_"+str(wid))
   must(not targets_absent(now[wid]) and len(now[wid]["structure"].get("polyline") or [])>0,
     "BUILDER_STILL_BROKEN_"+str(wid))
   print(json.dumps({"stage":"WRITE_VERIFIED","id":wid,"week":wk,"sport":now[wid]["workoutTypeValueId"]}),flush=True)
  final,fnote=await readall(c)
  must(fnote==notehash,"NOTES_CHANGED")
  must(set(z["workoutId"] for z in final)==set(byid),"WORKOUT_IDS_CHANGED")
  must(not any(targets_absent(z) for z in final),"BUILDER_INCOMPLETE_AFTER_FIX")
  must(all(stable(z)==expected[z["workoutId"]] for z in final),"UNEXPECTED_CHANGES")
  weekly_after={w:round(sum((z.get("totalTimePlanned") or 0)*60 for z in final if week(z)==w)) for w in range(1,25)}
  must(weekly_before==weekly_after,"WEEKLY_VOLUME_CHANGED")
  swims=[z for z in final if z["workoutId"] in (4001089818,4001089870)]
  must(all(z.get("distancePlanned")==1200 and
     abs(z["totalTimePlanned"]*60-30)<0.02 and z["structure"].get("primaryLengthMetric")=="distance"
     for z in swims),"SWIM_METERS_OR_DURATION_DRIFT")
  print(json.dumps({"stage":"PASS_249_NATIVE_BUILDER_QA","repaired":35,"no_missing_builder":True,
    "no_empty_active_targets":True,"polyline_present_all":True,
    "week_volume_unchanged_all24":True,"notes_unchanged":True,"all_ids_preserved":True,
    "plan_private":True,"no_athlete_write":True}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","reason":str(e)[:380]}),flush=True)
  raise
