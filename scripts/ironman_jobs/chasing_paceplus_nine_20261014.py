"""CHASING 685173: guarded nine-bike Pace/Pace+ split, fixed duration, no other workouts."""
import asyncio,copy,hashlib,json,re
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
from tp_mcp.tools.library import _ensure_structure_preview
P=685173;OWNER=2116886;PERSON=6682479
ANCHOR=date(2027,1,4)
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_paceplus_nine_20261014_backup.json"
# ID: relative week, weekday Mon=0, repetitions, original active minutes, Pace minutes, Pace+ minutes, rest minutes, lead/end extras
SETS={
4001050288:(10,3,3,15,10,5,15,15,25,10),
4001053067:(11,6,3,25,19,6,50,20,30,10),
4001058948:(13,1,3,12,8,4,8,15,45,10),
4001059223:(13,5,3,35,27,8,40,20,25,10),
4001062280:(14,5,2,30,20,10,55,20,15,10),
4001065433:(15,6,3,30,22,8,55,20,15,10),
4001071953:(17,1,3,12,8,4,8,15,45,10),
4001072083:(17,6,3,35,27,8,30,20,25,10),
4001074506:(18,3,2,20,14,6,25,20,45,10)
}
def need(c,msg):
 if not c:raise RuntimeError(msg)
def stable(w):return {k:v for k,v in w.items() if k!="lastModifiedDate"}
def sha(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def flat(s):return [z for g in s.get("structure") or [] for z in g.get("steps") or []]
def seconds(s):
 total=0
 for g in s.get("structure") or []:
  rep=int(g["length"]["value"]) if g.get("type")=="repetition" else 1
  total+=rep*sum(z["length"]["value"] for z in g.get("steps") or [])
 return total
def label(wid,row):
 wk,wd,reps,orig,pace,plus,rest,lead,finish,easy=SETS[wid]
 return (f"{lead}' avvio + {reps}x({pace}' Ironman Pace + {plus}' Ironman Pace+ + "
         f"{rest}' recupero facile) + {finish}' fondo facile + {easy}' defaticamento "
         f"= {lead+reps*(orig+rest)+finish+easy}' totali.")
def reword(description,wid):
 pat=r"(?ms)^STRUTTURA(?: AGGIORNATA)?(?:[ \t]*:[ \t]*|\n).*?(?=^(?:OBIETTIVO|INTENSITÀ|FUELING|NOTE)\b|\Z)"
 repl="STRUTTURA\n"+label(wid,None)+"\n\n"
 out,n=re.subn(pat,lambda m:repl,description,count=1)
 need(n==1 and out!=description,"DESCRIPTION_SHAPE_"+str(wid))
 need("Ironman Pace" in out and "Ironman Pace+" in out,"MISSING_LABEL")
 need(not re.search(r"\d+\s*[-–]\s*\d+\s*%\s*FTP",out,re.I),"TEXT_FTP_PERCENT")
 return out
def patched(w,wid):
 wk,wd,reps,orig,pace,plus,rest,lead,finish,easy=SETS[wid]
 day=ANCHOR+timedelta(days=(wk-1)*7+wd)
 need(str(w["workoutDay"])[:10]==day.isoformat(),"BAD_WEEK_DAY_"+str(wid))
 need(w.get("workoutId")==wid and w.get("workoutTypeValueId")==2,"BAD_ID_SPORT")
 need(abs(w["totalTimePlanned"]*60-(lead+reps*(orig+rest)+finish+easy))<0.01,"BAD_TOTAL_"+str(wid))
 st=w.get("structure") or {}
 need(st.get("primaryIntensityMetric")=="percentOfFtp" and st.get("primaryLengthMetric")=="duration","BAD_METRIC_"+str(wid))
 need(seconds(st)==round(w["totalTimePlanned"]*3600),"BUILDER_SUM_BEFORE_"+str(wid))
 need(not any("pace+" in (z.get("name") or "").lower() for z in flat(st)),"ALREADY_HAS_PACEPLUS_"+str(wid))
 groups=[g for g in st["structure"] if g.get("type")=="repetition"]
 need(len(groups)==1 and int(groups[0]["length"]["value"])==reps,"BAD_REPEAT_"+str(wid))
 g=groups[0]
 candidates=[i for i,z in enumerate(g.get("steps") or []) if z.get("intensityClass")=="active"]
 need(len(candidates)==1,"ACTIVE_STEPS_DRIFT_"+str(wid))
 index=candidates[0];src=g["steps"][index]
 need(src.get("length")=={"value":orig*60,"unit":"second"},"PACE_ORIG_DURATION_DRIFT_"+str(wid))
 need(len(src.get("targets") or [])==1,"PACE_TARGET_MISSING_"+str(wid))
 oldtarget=src["targets"][0]
 need(oldtarget==({"minValue":65,"maxValue":72} if wid==4001050288 else {"minValue":71,"maxValue":75}),"PACE_ORIG_INTENSITY_DRIFT_"+str(wid))
 need(all(k not in src for k in ("begin","end","workoutId","id")),"STEP_HAS_UNMODELED_COORDINATES")
 need(len(g["steps"])==2 and g["steps"][1-index].get("intensityClass")=="rest","RECOVERY_DRIFT_"+str(wid))
 other=g["steps"][1-index]
 need(other.get("length")=={"value":rest*60,"unit":"second"},"REST_LENGTH_DRIFT_"+str(wid))
 q=copy.deepcopy(w);sg=next(x for x in q["structure"]["structure"] if x.get("type")=="repetition")
 current=sg["steps"][index]
 current["name"]="Ironman Pace"
 current["length"]["value"]=pace*60
 current["targets"]=[{"minValue":71,"maxValue":75}]
 addition=copy.deepcopy(current)
 addition["name"]="Ironman Pace+"
 addition["length"]["value"]=plus*60
 addition["targets"]=[{"minValue":76,"maxValue":80}]
 sg["steps"].insert(index+1,addition)
 q["structure"].pop("polyline",None)
 q["structure"]=_ensure_structure_preview(q["structure"])
 need(seconds(q["structure"])==seconds(st),"BUILDER_SUM_AFTER_"+str(wid))
 need(len(q["structure"].get("polyline") or [])>=8,"POLYLINE_MISSING")
 q["description"]=reword(w.get("description") or "",wid)
 need(all(q[k]==w[k] for k in w if k not in ("structure","description")),"TOP_LEVEL_DRIFT_"+str(wid))
 ss=flat(q["structure"])
 need(any(z.get("name")=="Ironman Pace+" and z.get("targets")==[{"minValue":76,"maxValue":80}] for z in ss),"NO_PACEPLUS_TARGET")
 need(any(z.get("name")=="Ironman Pace" and z.get("targets")==[{"minValue":71,"maxValue":75}] for z in ss),"NO_NORMAL_PACE")
 return q
def week_window(wk):
 d=ANCHOR+timedelta(weeks=wk-1)
 return d.isoformat(),(d+timedelta(days=6)).isoformat()
async def readweek(c,wk):
 a,b=week_window(wk)
 rw=await c.get(f"/plans/v1/plans/{P}/workouts/{a}/{b}")
 rn=await c.get(f"/plans/v1/plans/{P}/calendarNote/{a}/{b}")
 need(not rw.is_error and not rn.is_error and isinstance(rw.data,list) and isinstance(rn.data,list),"WEEK_READ_"+str(wk))
 return rw.data,rn.data
async def main():
 async with TPClient() as c:
  me=await c._get_user_data()
  need(me.get("personId")==OWNER,"WRONG_OWNER")
  rp=await c.get(f"/plans/v1/plans/{P}")
  h=rp.data or {}
  need(not rp.is_error and h.get("planId")==P and h.get("planPersonId")==PERSON and h.get("isPublic") is False and h.get("workoutCount")==276 and "BOZZA" in (h.get("title") or ""),"WRONG_PLAN")
  weeks=sorted(set(z[0] for z in SETS.values()))
  observed={};noteshash={};byweek={}
  for wk in weeks:
   arr,notes=await readweek(c,wk)
   byweek[wk]={w["workoutId"]:stable(w) for w in arr}
   observed.update({w["workoutId"]:w for w in arr if w["workoutId"] in SETS})
   noteshash[str(wk)]=sha(notes)
  need(set(observed)==set(SETS),"NINE_TARGETS_NOT_FOUND")
  if BACKUP.exists():
   baseline=json.loads(BACKUP.read_text())
   need(baseline.get("plan")==P and set(map(int,baseline["original"]))==set(SETS),"BACKUP_SCOPE_DRIFT")
   need(baseline["notehash"]==noteshash,"NOTES_CHANGED_SINCE_BACKUP")
   originals={int(k):v for k,v in baseline["original"].items()}
  else:
   originals={wid:copy.deepcopy(w) for wid,w in observed.items()}
  desired={wid:patched(originals[wid],wid) for wid in SETS}
  pending=[]
  for wid,current in observed.items():
   if stable(current)==stable(desired[wid]):continue
   need(stable(current)==stable(originals[wid]),"UNKNOWN_LIVE_DRIFT_"+str(wid))
   pending.append(wid)
  if not BACKUP.exists():
   BACKUP.parent.mkdir(parents=True,exist_ok=True)
   BACKUP.write_text(json.dumps({"plan":P,"original":originals,"notehash":noteshash,"target_ids":list(SETS)},ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"PREFLIGHT_PASS","nine":len(SETS),"pending":len(pending),
   "all_duration_fixed":True,"notes_fixed":True,"backup":str(BACKUP),
   "splits":[{"id":wid,"week":v[0],"reps":v[2],"normal_min":v[4],"plus_min":v[5]} for wid,v in SETS.items()]},ensure_ascii=False),flush=True)
  # Golden first: only one workout is written on initial run. Remaining eight in next invocation.
  limit=1 if len(pending)==9 else len(pending)
  for wid in pending[:limit]:
   wk=SETS[wid][0]
   arr,notes=await readweek(c,wk)
   before={x["workoutId"]:stable(x) for x in arr}
   need(before[wid]==stable(originals[wid]) and sha(notes)==noteshash[str(wk)],"PREWRITE_DRIFT_"+str(wid))
   res=await c._request("PUT",f"/plans/v1/plans/{P}/workouts/{wid}",json=desired[wid],_retry_on_401=False)
   after,notes2=await readweek(c,wk)
   now={x["workoutId"]:stable(x) for x in after}
   need(not res.is_error and now.get(wid)==stable(desired[wid]),"PUT_NOT_VERIFIED_"+str(wid))
   need(sha(notes2)==noteshash[str(wk)],"NOTES_DRIFT_"+str(wid))
   need(all(now[k]==(stable(desired[wid]) if k==wid else v) for k,v in before.items()),"UNRELATED_WORKOUT_DRIFT_"+str(wid))
   print(json.dumps({"stage":"WRITE_VERIFIED","id":wid,"week":wk,"total_minutes":SETS[wid][7]+SETS[wid][2]*(SETS[wid][3]+SETS[wid][6])+SETS[wid][8]+SETS[wid][9]}),flush=True)
  if limit==1 and len(pending)==9:
   print(json.dumps({"stage":"GOLDEN_FIRST_PASS","written":1,"remaining":8}),flush=True)
  else:
   need(len(pending)==0 or limit==len(pending),"INCOMPLETE_BATCH")
   print(json.dumps({"stage":"NINE_PACEPLUS_PASS","verified":len(SETS),"remaining":0}),flush=True)
if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"SAFE_STOP","reason":str(e)[:450]}),flush=True)
  raise
