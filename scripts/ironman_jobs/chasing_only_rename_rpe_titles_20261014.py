"""CHASING-exclusive title-only rename of native Training Plan copies.
Conservative: exact 42 bike/run occurrences, 30 distinct current titles.
Never touch libraries, Beginner/Intermediate, athlete calendars, Builder,
description, RPE body, session dose, timing, week/day, native notes or swim.
"""
import asyncio,copy,hashlib,json,re
from pathlib import Path
from tp_mcp.client import TPClient

PLAN=685173
OWNER=2116886
PERSON=6682479
DATE_RANGES=(
 ("2027-01-04","2027-02-28"),
 ("2027-03-01","2027-04-25"),
 ("2027-04-26","2027-06-20"),
)
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_685173_titles_only_20261014_backup.json"

# Explicitly reviewed original CHASING plan-copy titles; excludes swim.
ALLOWED=(
 "Aerobico | 55' fondo facile RPE2-3",
 "Steady | 130' 3x8' RPE4-5 +12' recupero",
 "Brick | 15' transizione diagnostica e passo IM percepito, guida RPE 2-4",
 "Brick | 20' diagnostico con passo IM percepito, guida RPE 2-4",
 "Aerobico | 140' 3x15' aero controllata +15' easy, guida RPE 3-4",
 "Specifico | 120' 3x10' IM Bike Pace +20' easy, guida RPE 3-4",
 "Specifico | 4h45 3x25' IM Pace preliminare +50' easy, guida RPE 3-4",
 "Brick | 30' diagnostico con passo IM percepito, guida RPE 2-4",
 "Specifico | 130' 3x12' IM Pace +8' LT1, guida RPE 3-4",
 "Specifico | 175' 3x20' IM Pace +20' facile, guida RPE 3-4",
 "Lungo | 4h40 3x35' IM Pace +25' finale LT1, guida RPE 3-4",
 "Brick | 25' diagnostico IM Run Pace individuale, guida RPE 2-4",
 "Specifico | 165' 2x20' IM Pace +25' facile, guida RPE 3-4",
 "Lungo | 3h35 2x30' IM Pace +15' endurance finale, guida RPE 3-4",
 "Specifico | 205' 3x20' IM Pace +55' LT1, guida RPE 3-4",
 "Lungo | 5h 3x30' IM Pace +55' easy, guida RPE 3-4",
 "Specifico | 145' 2x25' IM Pace +10' easy, guida RPE 3-4",
 "Lungo | 4h10 3x35' IM Pace +25' LT1, guida RPE 3-4",
 "Specifico | 125' 2x10' IM Pace +20' easy, guida RPE 3-4",
 "Specifico | 130' 3x10' IM Pace +15' easy, guida RPE 3-4",
 "Aerobico | 100' fondo facile RPE2-3",
 "Specifico | 150' 3x15' IM Pace +15' facile, guida RPE 3-4",
 "Lungo | 4h55 3x30' IM Pace +35' fondo facile, guida RPE 3-4",
 "Recupero | 130' endurance sotto LT1 RPE2",
 "Recupero | 80' corsa lenta RPE2",
 "Specifico | 150' 3x10' IM Pace +50' LT1, guida RPE 3-4",
 "Specifico | 225' 2x20' IM Pace +55' facile, guida RPE 3-4",
 "Specifico | 125' 2x8' IM Pace +16' easy, guida RPE 3-4",
 "Attivazione | 40' 3x2' IM Pace rilassato, RPE 2-3",
 "Attivazione | 20' 2x1' IM Pace familiare, guida RPE 2-3",
)
STEADY="Steady | 130' 3x8' RPE4-5 +12' recupero"
STEADY_NEW="Tempo | 130' con 3x8' steady e 12' recupero"
TRAIL=re.compile(r"(?:,\s*guida\s+RPE\s*\d+(?:\s*[-–]\s*\d+)?|,\s*RPE\s*\d+(?:\s*[-–]\s*\d+)?|\s+RPE\s*\d+(?:\s*[-–]\s*\d+)?)$",re.I)

def require(condition,message):
 if not condition:raise RuntimeError(message)
def cleanobj(w):
 return {k:v for k,v in w.items() if k!="lastModifiedDate"}
def checksum(obj):
 return hashlib.sha256(json.dumps(obj,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
def newtitle(t):
 if t==STEADY: return STEADY_NEW
 z=TRAIL.sub("",t)
 require(z!=t and not re.search(r"\bRPE",z,re.I),"UNHANDLED_RPE_TITLE:"+t)
 require(z.count("|")==1 and all(z.split("|")) and "CHASING" not in z and "W0" not in z,"BAD_NAMING:"+z)
 return z

async def block(c,i):
 a,b=DATE_RANGES[i]
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{a}/{b}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{a}/{b}")
 require(not w.is_error and not n.is_error and isinstance(w.data,list) and isinstance(n.data,list),"PLAN_BLOCK_READ_FAILED")
 return w.data,checksum(n.data)

async def snapshot(c):
 blocks=await asyncio.gather(*[block(c,i) for i in range(3)])
 rows=[w for x in blocks for w in x[0]]
 require(len(rows)==249 and len({w["workoutId"] for w in rows})==249,"UNEXPECTED_249_WORKOUTS")
 return rows,[x[1] for x in blocks]

async def main():
 require(len(ALLOWED)==30 and len(set(ALLOWED))==30,"ALLOWED_MISMATCH")
 mapping={title:newtitle(title) for title in ALLOWED}
 async with TPClient() as c:
  user=await c._get_user_data()
  require(user.get("personId")==OWNER,"WRONG_OWNER")
  p=await c.get(f"/plans/v1/plans/{PLAN}")
  h=p.data
  require(not p.is_error and h.get("planId")==PLAN and h.get("planPersonId")==PERSON
          and h.get("isPublic") is False and h.get("workoutCount")==276
          and "BOZZA" in (h.get("title") or ""),"WRONG_PLAN")
  rows,notes=await snapshot(c)
  found=[w for w in rows if w.get("workoutTypeValueId") in (2,3) and re.search(r"\bRPE",w.get("title") or "",re.I)]
  if BACKUP.exists():
   bak=json.loads(BACKUP.read_text())
   require(bak.get("plan")==PLAN and len(bak.get("original",[]))==249,"BACKUP_NOT_VALID")
   base=bak["original"]
   require(bak.get("notes")==notes,"BACKUP_NOTE_HASH_DRIFT")
  else:
   require(len(found)==42 and len({w["title"] for w in found})==30,"EXPECTED_42_SOURCE_RPE_TITLES")
   require(set(w["title"] for w in found)==set(ALLOWED),"UNREVIEWED_TITLE_DETECTED")
   require(sum(w["workoutTypeValueId"]==2 for w in found)==27 and sum(w["workoutTypeValueId"]==3 for w in found)==15,"WRONG_SPORT_COUNTS")
   base=rows
   BACKUP.parent.mkdir(parents=True,exist_ok=True)
   BACKUP.write_text(json.dumps({"plan":PLAN,"original":rows,"notes":notes,"title_map":mapping},ensure_ascii=False,indent=2)+"\n")
  desired={}
  for w in base:
   new=copy.deepcopy(w)
   if w.get("workoutTypeValueId") in (2,3) and w.get("title") in mapping:
    new["title"]=mapping[w["title"]]
   desired[w["workoutId"]]=cleanobj(new)
  targets=[w["workoutId"] for w in base if w.get("workoutTypeValueId") in (2,3) and w.get("title") in mapping]
  require(len(targets)==42 and len(set(targets))==42,"EXPECTED_42_TARGET_IDS")
  current={w["workoutId"]:cleanobj(w) for w in rows}
  for w in base:
   wid=w["workoutId"]
   require(current[wid] in (cleanobj(w),desired[wid]),"UNEXPECTED_PROVIDER_DRIFT_"+str(wid))
  pending=[wid for wid in targets if current[wid]!=desired[wid]]
  print(json.dumps({"stage":"PREFLIGHT_PASS","target_instances":42,"distinct_titles":30,
                    "pending":len(pending),"already_done":42-len(pending),
                    "plan":PLAN,"backup":str(BACKUP)}),flush=True)
  for seq,wid in enumerate(pending,1):
   original=next(w for w in base if w["workoutId"]==wid)
   idx=next(i for i,(a,b) in enumerate(DATE_RANGES) if a<=str(original["workoutDay"])[:10]<=b)
   before,nh=await block(c,idx)
   require(nh==notes[idx],"NOTES_CHANGED")
   require({w["workoutId"]:cleanobj(w) for w in before}[wid]==cleanobj(original),"TARGET_NOT_ORIGINAL_BEFORE_"+str(wid))
   updated=copy.deepcopy(original)
   updated["title"]=mapping[original["title"]]
   require(all(updated[k]==original[k] for k in original if k!="title"),"PAYLOAD_NOT_TITLE_ONLY")
   response=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",json=updated,_retry_on_401=False)
   after,nh2=await block(c,idx)
   require(nh2==notes[idx],"NOTES_CHANGED_AFTER")
   actual={w["workoutId"]:cleanobj(w) for w in after}
   if response.is_error and actual.get(wid)!=desired[wid]:
    raise RuntimeError("PUT_ERROR_AND_NOT_APPLIED_"+str(wid))
   require(actual.get(wid)==desired[wid],"TITLE_NOT_READBACK_VERIFIED_"+str(wid))
   require(all(actual.get(k)==desired[k] if k in targets and current[k]==desired[k] or k==wid
               else actual.get(k)==current[k] for k in actual if k!=wid),"OTHER_WORKOUT_DRIFT_"+str(wid))
   current[wid]=desired[wid]
   if seq%10==0:print(json.dumps({"stage":"VERIFIED_PROGRESS","processed":seq,"pending_start":len(pending)}),flush=True)
  final,nfinal=await snapshot(c)
  require(nfinal==notes,"FINAL_NOTES_CHANGED")
  require(all(cleanobj(w)==desired[w["workoutId"]] for w in final),"FINAL_WORKOUT_FIELDS_DRIFT")
  require(not [w for w in final if w.get("workoutTypeValueId") in (2,3) and re.search(r"\bRPE",w.get("title") or "",re.I)],"RPE_TITLE_REMAINS")
  print(json.dumps({"stage":"PASS_42_TITLE_ONLY","total_renamed":42,"changed_this_run":len(pending),
                    "plan":PLAN,"other_207_workouts_unchanged":True,
                    "swim_titles_unchanged":True,"native_builders_unchanged":True,
                    "descriptions_unchanged":True,"athlete_and_library_writes":0}),flush=True)

if __name__=="__main__":
 try:
  asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RECONCILE","error":str(e)[:440]}),flush=True)
  raise
