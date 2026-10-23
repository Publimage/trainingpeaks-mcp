"""Beginner 679801 native %FTP -> RPE translation, strict by workout role.
Source: approved Product Spec; never extrapolate by linear FTP->RPE formula.
"""
import copy,hashlib,json
from datetime import date,timedelta
from pathlib import Path
from tp_mcp.tools.library import _ensure_structure_preview
PLAN=679801
OWNER=2116886
MANIFEST=Path("data/ironman_manifests/beginner_rpe_primary_41_bikes_20261016.json")
def need(ok,msg):
 if not ok:raise RuntimeError(msg)
def stable(w):return {k:v for k,v in w.items() if k!="lastModifiedDate"}
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def load_manifest():
 m=json.loads(MANIFEST.read_text(encoding="utf-8"))
 need(m.get("plan_id")==PLAN and m.get("schema")=="BEGINNER_NATIVE_RPE_PRIMARY_AUDIT_MANIFEST_V1","WRONG_MANIFEST")
 rows=m.get("rpe_bike_conversion_candidates") or []
 need(len(rows)==41 and len({r["id"] for r in rows})==41,"MANIFEST_COUNT")
 need(all(r.get("source_rpe_clauses") and r.get("current_metric")=="percentOfFtp" for r in rows),"RPE_SOURCE_MISSING")
 return {r["id"]:r for r in rows}
def flat(s):
 return [z for g in s.get("structure") or [] for z in g.get("steps") or []]
def rpe_for(row,step):
 cl=step.get("intensityClass")
 name=(step.get("name") or "").lower()
 title=row.get("title","").lower()
 if cl in ("warmUp","rest","coolDown"):return (1,2)
 need(cl=="active","UNKNOWN_STEP_CLASS_"+str(row["id"])+":"+str(cl))
 if "sotto soglia" in name:return (6,6)
 if "sopra soglia" in name:return (7,8)
 if "vo2" in name:return (8,8)
 if "soglia" in name:return (7,7)
 if "sfr/pfr" in name:return (6,7)
 if "bassa cadenza" in name:return (5,5)
 if "benchmark steady" in name or name=="steady":return (4,4)
 if "cadenza agile" in name or "agilit" in name:return (2,3)
 if ("molto facile" in name or "aerobico facile" in name or
     "endurance bassa" in name or
     (title.startswith("aerobico") and "endurance" in name)):return (1,2)
 if any(x in name for x in ("endurance","aero","facile")):return (2,3)
 raise RuntimeError("UNMAPPED_ACTIVE_ROLE_"+str(row["id"])+":"+name)
def native_seconds(st):
 total=0
 for g in st.get("structure") or []:
  rep=int((g.get("length") or {}).get("value",1)) if g.get("type")=="repetition" else 1
  for s in g.get("steps") or []:
   l=s.get("length") or {}
   need(l.get("unit")=="second" and type(l.get("value")) in (int,float),"INVALID_STEP_LENGTH")
   total+=rep*l["value"]
 return total
def patch(w,row):
 wid=w["workoutId"]
 need(wid==row["id"] and w["workoutTypeValueId"]==2,"WORKOUT_ID_OR_SPORT_DRIFT")
 need(w.get("title")==row["title"],"TITLE_DRIFT_"+str(wid))
 s=w.get("structure") or {}
 need(s.get("primaryIntensityMetric")=="percentOfFtp" and s.get("primaryLengthMetric")=="duration","METRIC_DRIFT_"+str(wid))
 steps=flat(s);need(steps and len(steps)<=40,"STEP_COUNT_"+str(wid))
 original_seconds=native_seconds(s)
 need(abs(original_seconds-(w.get("totalTimePlanned") or 0)*3600)<1,"ORIGINAL_DURATION_DRIFT_"+str(wid))
 q=copy.deepcopy(w);n=q["structure"];seen_cadence=0
 for step in flat(n):
  t=step.get("targets") or []
  need(t and type(t[0].get("minValue")) in (int,float) and type(t[0].get("maxValue")) in (int,float),"MISSING_TARGET_"+str(wid))
  extras=copy.deepcopy(t[1:])
  need(all(x.get("unit")=="roundOrStridePerMinute" for x in extras),"UNKNOWN_EXTRA_TARGET_"+str(wid))
  seen_cadence+=len(extras)
  lo,hi=rpe_for(row,step)
  step["targets"]=[{"minValue":lo,"maxValue":hi}]+extras
 n["primaryIntensityMetric"]="rpe";n["primaryIntensityTargetOrRange"]="range";n.pop("polyline",None)
 q["structure"]=_ensure_structure_preview(n)
 need(len(q["structure"].get("polyline") or [])>=4,"NEW_POLYLINE_MISSING_"+str(wid))
 need(all(q[k]==w[k] for k in w if k!="structure"),"TOP_LEVEL_DRIFT_"+str(wid))
 need(native_seconds(q["structure"])==original_seconds,"DOSE_CHANGED_"+str(wid))
 for a,b in zip(flat(s),flat(q["structure"])):
  aa=copy.deepcopy(a);bb=copy.deepcopy(b)
  aa.pop("targets",None);bb.pop("targets",None)
  need(aa==bb,"STEP_DOSE_OR_ORDER_DRIFT_"+str(wid))
  need(a.get("targets",[])[1:]==b.get("targets",[])[1:],"CADENCE_CHANGED_"+str(wid))
 need(len(flat(s))==len(flat(q["structure"])),"STEP_COUNT_CHANGED_"+str(wid))
 return q,{"id":wid,"week":row["week"],"old_metric":"percentOfFtp","new_metric":"rpe",
           "minutes":round(original_seconds/60,1),"steps":len(steps),"cadence_fields":seen_cadence,
           "polyline_points":len(q["structure"]["polyline"])}
async def fetch_all(c,anchor):
 result={}
 notes=[]
 for n in range(3):
  start=anchor+timedelta(weeks=n*8);end=start+timedelta(days=55)
  a=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{start.isoformat()}/{end.isoformat()}")
  b=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{start.isoformat()}/{end.isoformat()}")
  need(not a.is_error and isinstance(a.data,list) and not b.is_error,"READ_PART_"+str(n))
  for w in a.data:
   need(w["workoutId"] not in result,"DUPLICATE_WORKOUT")
   result[w["workoutId"]]=w
  notes.append(b.data)
 need(len(result)==254,"COUNT_DRIFT_"+str(len(result)))
 return result,digest(notes)
async def get_plan(c):
 u=await c._get_user_data();need(u.get("personId")==OWNER,"WRONG_COACH")
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 need(not p.is_error and isinstance(p.data,dict),"PLAN_UNAVAILABLE")
 h=p.data
 need(h.get("planId")==PLAN and h.get("isPublic") is True and h.get("workoutCount")==254 and "Beginner" in (h.get("title") or ""),"PLAN_GUARD")
 return date.fromisoformat(str(h["startDate"])[:10])
async def preflight(c):
 anchor=await get_plan(c)
 before,nh=await fetch_all(c,anchor)
 manifest=load_manifest()
 compiled={}
 for wid,row in manifest.items():
  w=before.get(wid);need(w is not None,"MISSING_"+str(wid))
  week=1+(date.fromisoformat(str(w["workoutDay"])[:10])-anchor).days//7
  need(week==row["week"],"REL_WEEK_DRIFT_"+str(wid))
  compiled[wid]=patch(w,row)
 need(len(compiled)==41,"COMPILED_COUNT")
 return before,nh,compiled,anchor
