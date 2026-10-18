"""Repair wording and round Builder steps of 70.3 Beginner plan AND shared source templates.
Every changed template is identified by provider ID, never edited by title alone.
Uses immutable preflight manifest and readback. Six strictly scoped stages of 20 workout slots.
"""
import asyncio,copy,hashlib,json,re
from pathlib import Path
from datetime import date,timedelta
from tp_mcp.client import TPClient
try:
 from scripts.ironman_jobs.half_beginner_16w_prod import items,ANCHOR
except ModuleNotFoundError:
 from half_beginner_16w_prod import items,ANCHOR
PLAN=686994;OWNER=2116886
TITLE="ALBERTO FAZI ENDURANCE | 70.3 | 16 settimane | Beginner | Italiano"
LIB={1:3891872,2:3892601,3:3892602}
STATE=Path.home()/".trainingpeaks-mcp/half_beginner_16w_rounding_manifest_20261018.json"
STAGES=6
def need(a,msg):
 if not a:raise RuntimeError(msg)
def minute(x):
 return 5*int((float(x)+2.5)//5)
def block(name,mi,lo,hi,cls,at):
 n=mi*60
 return {"type":"step","length":{"value":1,"unit":"repetition"},
 "steps":[{"name":name,"length":{"value":n,"unit":"second"},"targets":[{"minValue":lo,"maxValue":hi}],
 "intensityClass":cls,"openDuration":False}],"begin":at,"end":at+n}
def cleanstr(s):
 if not isinstance(s,str):return s
 # A previous mass-build introduced literal two-character backslash + n.
 out=s.replace("\\\\n","\\n").replace("\\n","\n").replace("\\r","\r")
 return out
def fixstructure(sport,m,old_title):
 if sport==1:return None
 is_long=("Lungo |" in old_title)
 is_brick=("Brick |" in old_title)
 is_steady=("controllo RPE3-4" in old_title)
 if sport==2:
  warm=15 if m>=80 else 10 if m>=40 else 5
  cool=10 if m>=120 else 5
  if is_long:vals=[("Avvio aerobico",warm,1,2,"warmUp"),("Lungo sotto controllo",m-warm-cool,2,3,"active"),("Defaticamento",cool,1,2,"coolDown")]
  elif is_steady:
   q=25 if m>=85 else 20 if m>=65 else 10
   need(m-warm-cool-q>=10,"BIKE_SEGMENT_TOO_SHORT")
   vals=[("Riscaldamento",warm,1,2,"warmUp"),("Fondo facile",m-warm-cool-q,2,3,"active"),
   ("Controllo regolare senza soglia",q,3,4,"active"),("Ritorno facile",cool,1,2,"coolDown")]
  else:vals=[("Riscaldamento",warm,1,2,"warmUp"),("Fondo facile",m-warm-cool,2,3,"active"),("Ritorno facile",cool,1,2,"coolDown")]
 else:
  warm=0 if is_brick else 10 if m>=60 else 5
  cool=5 if m>=15 else 0
  vals=[("Avvio lento",warm,1,2,"warmUp"),("Corsa facile continua",m-warm-cool,2,3,"active"),("Chiusura molto facile",cool,1,2,"coolDown")]
  if is_brick:
   vals=[("Corsa di transizione facile",m-cool,2,3,"active"),("Chiusura facile",cool,1,2,"coolDown")]
 need(all(v[1]>0 and v[1]%5==0 for v in vals),"BAD_ROUND_COMPONENTS")
 parts=[];pos=0
 for name,mi,lo,hi,cl in vals:
  z=block(name,mi,lo,hi,cl,pos);parts.append(z);pos=z["end"]
 need(pos==m*60,"BAD_BUILDER_TOTAL")
 structure={"structure":parts,"primaryLengthMetric":"duration","primaryIntensityMetric":"rpe",
 "primaryIntensityTargetOrRange":"range"}
 poly=[];maxy=max(z["steps"][0]["targets"][0]["maxValue"] for z in parts)
 for b in parts:
  st=b["begin"]/(m*60);en=b["end"]/(m*60);y=round(b["steps"][0]["targets"][0]["maxValue"]/maxy,4)
  poly.extend([[round(st,4),0],[round(st,4),y],[round(en,4),y],[round(en,4),0]])
 structure["polyline"]=poly
 return structure
def spec(sport,src):
 m=minute(src.get("totalTimePlanned",0)*60)
 need(m>=10,"SHORT_WORKOUT")
 orig=src["itemName"]
 title=orig
 if sport in (2,3):
  title=re.sub(r"\b\d{1,3}'",f"{m}'",orig,count=1)
 desc=cleanstr(src.get("description") or "")
 # Normalize display, not athlete content or fixed-pacing prescriptions.
 desc=desc.replace("\r\n","\n").replace("\r","\n")
 desc=re.sub(r"\n{3,}","\n\n",desc).strip()
 if sport==2 and m>=90 and "ALIMENTAZIONE\nAcqua secondo sete" in desc:
  desc=desc.replace("ALIMENTAZIONE\nAcqua secondo sete e condizioni, alimentazione ordinaria per durata breve.",
    "ALIMENTAZIONE\nPer sedute da 90 minuti e oltre verifica acqua e carburazione secondo durata, intensità e tolleranza; prova gradualmente carboidrati prima delle settimane lunghe.")
 st=src.get("structure")
 need(isinstance(st,dict) and isinstance(st.get("structure"),list),"SOURCE_NOT_NATIVE")
 new=copy.deepcopy(st) if sport==1 else fixstructure(sport,m,orig)
 if sport==1:
  new["polyline"]=st.get("polyline") or []
 need(not re.search(r"\bW\d\d\b|70\.3",title,re.I),"PUBLIC_TITLE_CODE")
 need(all(abs((b["end"]-b["begin"])%300)<1 for b in new["structure"]) if sport!=1 else True,"NONROUND_STEP")
 return {"title":title,"description":desc,"minutes":m,"structure":new,
         "distance":src.get("distancePlanned"),"sport":sport}
def unchanged(old,target):
 return (old.get("itemName")==target["title"] and old.get("description")==target["description"]
     and abs(float(old.get("totalTimePlanned") or 0)*60-target["minutes"])<.0001
     and old.get("structure")==target["structure"])
def calendar_match(v,target):
 rawstruct=v.get("structure")
 if isinstance(rawstruct,str):
  try:rawstruct=json.loads(rawstruct)
  except ValueError:return False
 return v.get("title")==target["title"] and v.get("description")==target["description"] and abs(float(v.get("totalTimePlanned") or 0)*60-target["minutes"])<.0001 and rawstruct==target["structure"]
async def run():
 async with TPClient() as c:
  me=await c._get_user_data();p=await c.get(f"/plans/v1/plans/{PLAN}")
  need(isinstance(me,dict) and me.get("personId")==OWNER,"OWNER_GUARD")
  need(not p.is_error and p.data.get("title")==TITLE and p.data.get("isPublic") is False
  and p.data.get("workoutCount") in range(118,134),"PLAN_SCOPE")
  async def cal():
   v=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{ANCHOR.isoformat()}/{(ANCHOR+timedelta(days=112)).isoformat()}")
   need(not v.is_error and isinstance(v.data,list),"CAL_READ_FAIL")
   return v.data
  now=await cal()
  classic=[v for v in now if v.get("workoutTypeValueId") in (1,2,3)]
  need(len(classic)==118 and len({v["workoutId"] for v in classic})==118,"CLASSIC_SET")
  libraries={}
  for sp,lid in LIB.items():
   r=await c.get(f"/exerciselibrary/v2/libraries/{lid}/items")
   need(not r.is_error and isinstance(r.data,list),"LIB_GET")
   libraries[sp]={int(x["exerciseLibraryItemId"]):x for x in r.data}
  if STATE.exists():
   saved=json.loads(STATE.read_text(encoding="utf8"))
   need(saved["plan"]==PLAN and len(saved["rows"])==118 and len(saved["specs"])>=70,"BACKUP_CONTRACT")
   print(json.dumps({"stage":"MANIFEST_RESTORED","entries":len(saved["rows"]),"unique":len(saved["specs"])}),flush=True)
  else:
   rows=[];specs={}
   for v in sorted(classic,key=lambda a:(a["workoutDay"],a["workoutId"])):
    sp=v["workoutTypeValueId"]
    candidates=[x for x in libraries[sp].values() if x["itemName"]==v["title"] and x.get("description")==v.get("description")
        and abs((x.get("totalTimePlanned") or 0)-(v.get("totalTimePlanned") or 0))<1e-5]
    need(len(candidates)==1,"SOURCE_TEMPLATE_AMBIGUOUS_"+str(v["workoutId"])+"_"+str(len(candidates)))
    source=candidates[0];sid=int(source["exerciseLibraryItemId"])
    need(sid>=15000000,"PROTECT_EXISTING_FULL_LIBRARY")
    key=str(sid)
    if key not in specs:specs[key]={"library":LIB[sp],"old":copy.deepcopy(source),"target":spec(sp,source)}
    uid={"id":int(v["workoutId"]),"source_id":sid,"week":(date.fromisoformat(v["workoutDay"][:10])-ANCHOR).days//7+1,
        "sport":sp,"original":copy.deepcopy(v)}
    rows.append(uid)
   need(len(rows)==118,"MANIFEST_118")
   # prevent target-title collisions across incompatible prescriptions.
   names={}
   for key,entry in specs.items():
    t=entry["target"];name=(entry["library"],t["title"])
    names.setdefault(name,[]).append((key,entry))
   for (lib,name),group in names.items():
    if len(group)<=1:continue
    first=group[0][1]["target"]
    for index,(key,v) in enumerate(group):
     if index==0:continue
     if v["target"]!=first:
      signature="RPE2-3 facile" if "controllo RPE" not in name else "controllo specifico"
      v["target"]["title"]+=f" | {signature} {index+1}"
    # Identical target variants remain distinct library IDs until deduplication audit.
   saved={"plan":PLAN,"rows":rows,"specs":specs}
   STATE.parent.mkdir(parents=True,exist_ok=True)
   STATE.write_text(json.dumps(saved,ensure_ascii=False,indent=2,default=str),encoding="utf8")
   print(json.dumps({"stage":"MANIFEST_FROZEN","rows":len(rows),"templates":len(specs)}),flush=True)
  rows=saved["rows"];specs=saved["specs"]
  stage=int(__import__("os").environ.get("HALF_FIX_STAGE","0"))
  # Operator jobs are statically wrapper scripts setting their own stage; fallback: first incomplete 20-row block.
  groups=[rows[i:i+20] for i in range(0,len(rows),20)]
  selected=None;last=None
  by_id={v["workoutId"]:v for v in classic}
  for ix,g in enumerate(groups):
   complete=all(calendar_match(by_id[r["id"]],specs[str(r["source_id"])]["target"]) for r in g)
   if not complete:selected=(ix+1,g);break
  if selected is None:
   print(json.dumps({"stage":"ALL_118_FORMAT_CORRECT","plan":PLAN,"templates":len(specs)}),flush=True);return 0
  idx,g=selected
  print(json.dumps({"stage":"PATCH_PREFLIGHT","batch":idx,"workouts":len(g),"total":118,"templates":len(specs)}),flush=True)
  written=0;templ=0
  for row in g:
   sid=str(row["source_id"]);src=specs[sid];target=src["target"];old=src["old"]
   sp=target["sport"];lid=src["library"]
   v=by_id[row["id"]]
   if calendar_match(v,target):continue
   current=libraries[sp].get(int(sid))
   need(current is not None and int(current["exerciseLibraryItemId"])==int(sid),"TEMPLATE_ID_DRIFT")
   if not unchanged(current,target):
    # Existing state must be exactly the frozen original or the requested target.
    need(current==old,"SOURCE_DRIFT_NO_BLIND_OVERWRITE_"+sid)
    payload=copy.deepcopy(current)
    payload["itemName"]=target["title"]
    payload["description"]=target["description"]
    payload["totalTimePlanned"]=target["minutes"]/60
    payload["structure"]=target["structure"]
    res=await c._request("PUT",f"/exerciselibrary/v1/libraries/{lid}/items/{sid}",json=payload,_retry_on_401=False)
    fresh=await c.get(f"/exerciselibrary/v2/libraries/{lid}/items")
    need(not fresh.is_error and isinstance(fresh.data,list),"LIBRARY_POST_READBACK_FAIL")
    hit=[x for x in fresh.data if int(x.get("exerciseLibraryItemId") or -1)==int(sid)]
    need(len(hit)==1 and unchanged(hit[0],target),"LIBRARY_PATCH_UNVERIFIED_"+sid)
    libraries[sp][int(sid)]=hit[0]
    need(not res.is_error,"LIBRARY_WRITE_RESULT_UNCERTAIN_"+sid)
    templ+=1
   # Verify exact initial plan snapshot unless already patched on a previous interrupted run.
   orig=row["original"]
   need(v==orig,"PLAN_WORKOUT_DRIFT_"+str(row["id"]))
   payload=copy.deepcopy(v);payload["title"]=target["title"];payload["description"]=target["description"]
   payload["totalTimePlanned"]=target["minutes"]/60
   payload["structure"]=json.dumps(target["structure"],ensure_ascii=False,separators=(",",":"))
   res=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{row['id']}",json=payload,_retry_on_401=False)
   query=await cal()
   hits=[x for x in query if x.get("workoutId")==row["id"]]
   need(len(hits)==1 and calendar_match(hits[0],target),"PLAN_PATCH_UNVERIFIED_"+str(row["id"]))
   need(not res.is_error,"PLAN_PATCH_RESULT_UNCERTAIN_"+str(row["id"]))
   by_id[row["id"]]=hits[0]
   written+=1
  print(json.dumps({"stage":"PATCH_BATCH_COMPLETE","batch":idx,"patched":written,"library_templates":templ,
    "plan":PLAN,"expected_rows":len(g),"public":False,"athletes":0}),flush=True)
  return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(run()))
 except Exception as e:
  print(json.dumps({"stage":"PATCH_STOP","error":str(e),"kind":type(e).__name__}),flush=True)
  raise SystemExit(97)
