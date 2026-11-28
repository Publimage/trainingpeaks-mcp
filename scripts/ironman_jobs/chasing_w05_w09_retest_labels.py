"""Rename W05 and W09 post-deload test copies as RETEST on CHASING private plan.
Plan-scoped in place. No change to structure, intensity, dose, dates, workout IDs.
"""
import asyncio,json,hashlib
from pathlib import Path
from tp_mcp.client import TPClient
OWNER=2116886
PERSON=6682479
PLAN=685173
TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
ANCHOR="2027-01-04"
START="2027-02-01"
END="2027-03-07"
SPEC=[
 {"id":4000954221,"date":"2027-02-03","sport":1,
  "old":"Test | T1500 iniziale - 2500 m","title":"Test | RETEST W05 | T1500 - 2500 m",
  "intro":"RETEST W05 dopo la settimana di assorbimento W04. Confronta T1500 con la baseline W01 nello stesso tipo di vasca, a parità ragionevole di alimentazione, orario e gestione del passo; non trasformare l'eventuale variazione in una certezza fisiologica.\n\n"},
 {"id":4000954256,"date":"2027-02-04","sport":2,
  "old":"Test | 20' potenza sostenibile - 60'","title":"Test | RETEST W05 | 20' potenza - 60'",
  "intro":"RETEST W05 dopo lo scarico W04. Ripeti il protocollo baseline W01 di 20 minuti, idealmente stesso misuratore/tratto, condizioni comparabili e pacing regolare. Non impostare automaticamente LT2 o FTP usando un fattore fisso.\n\n"},
 {"id":4001048397,"date":"2027-03-03","sport":1,
  "old":"Test | T1500 iniziale - 2500 m","title":"Test | RETEST W09 | T1500 - 2500 m",
  "intro":"RETEST W09 dopo assorbimento W08. Controlla coerenza con W01 e W05, mantenendo riferimenti di vasca, setup, disponibilità energetica e pacing il più possibile replicabili. Non ritestare se recupero insufficiente: applicare l'alternativa conservativa della guida.\n\n"},
]
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_w05_w09_retest_editorial_backup.json"
def must(x,msg):
 if not x:raise RuntimeError(msg)
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()
def stable(x):return {k:v for k,v in x.items() if k!="lastModifiedDate"}
async def read(c):
 p=await c.get(f"/plans/v1/plans/{PLAN}")
 must(not p.is_error and isinstance(p.data,dict),"PLAN_GET_FAIL")
 m=p.data
 must(m.get("planId")==PLAN and m.get("planPersonId")==PERSON and m.get("title")==TITLE and
      m.get("isPublic") is False and m.get("price") in (None,0) and
      m.get("workoutCount")==276 and str(m.get("startDate") or "")[:10]==ANCHOR,"WRONG_PLAN")
 w=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{START}/{END}")
 n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{START}/{END}")
 must(not w.is_error and not n.is_error and isinstance(w.data,list) and isinstance(n.data,list),"BLOCK_READ_FAIL")
 return w.data,digest(n.data)

async def main():
 async with TPClient() as c:
  u=await c._get_user_data()
  must(u.get("personId")==OWNER,"WRONG_OWNER")
  before,notes=await read(c)
  sources=[]
  for v in SPEC:
   hit=[w for w in before if w.get("workoutId")==v["id"]]
   must(len(hit)==1,"WORKOUT_NOT_FOUND")
   x=hit[0]
   must(x.get("title")==v["old"] and x.get("workoutTypeValueId")==v["sport"] and
        str(x.get("workoutDay") or "")[:10]==v["date"] and isinstance(x.get("structure"),dict),
        "RETEST_CANDIDATE_CHANGED")
   sources.append(x)
  ids=sorted(v.get("workoutId") for v in before)
  must(not BACKUP.exists(),"BACKUP_EXISTS_REVIEW")
  BACKUP.parent.mkdir(parents=True,exist_ok=True)
  BACKUP.write_text(json.dumps({"before":before,"note_sha256":notes,"plan":PLAN},ensure_ascii=False,indent=2)+"\n")
  print(json.dumps({"stage":"RETEST_PREFLIGHT","count":len(before),"updates":len(SPEC)}),flush=True)
  for i,(v,old) in enumerate(zip(SPEC,sources)):
   current,_=await read(c)
   x=[z for z in current if z.get("workoutId")==v["id"]]
   must(len(x)==1 and x[0].get("title")==v["old"],f"DRIFT_{i}")
   put=dict(old)
   put["title"]=v["title"]
   base=old.get("description") or ""
   base=base.replace("Questo è il primo riferimento nuoto del piano",
                     "Questo è un retest, da confrontare con la baseline del piano")
   put["description"]=v["intro"]+base
   result=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{v['id']}",
             json=put,_retry_on_401=False)
   after,newnotes=await read(c)
   y=[z for z in after if z.get("workoutId")==v["id"]]
   must(len(y)==1 and not result.is_error and y[0].get("title")==v["title"] and
        y[0].get("description")==put["description"],f"EDIT_NOT_VERIFIED_{i}")
   must({k:z for k,z in y[0].items() if k not in ("title","description","lastModifiedDate")}==
        {k:z for k,z in old.items() if k not in ("title","description","lastModifiedDate")},
        f"PHYSIOLOGICAL_CONTENT_CHANGED_{i}")
   must(sorted(z.get("workoutId") for z in after)==ids and newnotes==notes,
        f"NOTE_OR_ID_CHANGED_{i}")
   print(json.dumps({"stage":"RETEST_LABEL_VERIFIED","id":v["id"],"date":v["date"],
      "sport":v["sport"],"title":v["title"],"structure_unchanged":True}),flush=True)
  end,finalnotes=await read(c)
  must(sorted(z.get("workoutId") for z in end)==ids and finalnotes==notes,"FINAL_FAIL")
  print(json.dumps({"stage":"RETEST_W05_W09_PASS","edits":3,"plan":PLAN,
      "all_ids_preserved":True,"all_native_structures_preserved":True,
      "public":False,"no_athlete_calendar":True}),flush=True)

if __name__=="__main__":
 try:asyncio.run(main())
 except Exception as e:
  print(json.dumps({"stage":"STOP_RETEST","reason":str(e)[:270],"no_blind_retry":True}),flush=True)
  raise
