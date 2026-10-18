"""Add 15 native Builder strength sessions to private Half Beginner 16W plan only."""
import asyncio,json
from datetime import date,timedelta
import httpx
from tp_mcp.client import TPClient
from tp_mcp.tools.strength import _access,_headers,STRENGTH_API_BASE,_build_payload,_validate_blocks
from scripts.ironman_jobs.half_beginner_16w_prod import MATRIX,ANCHOR,TITLE,items
OWNER=2116886;PLAN=686994;BASE="/rx/activity/v1"
EXPECTED=118
def must(cond,msg):
 if not cond:raise RuntimeError(msg)
def work():
 return [r for r in items() if r["sport"]=="ST"]
def title(minutes,w):
 if w<=4:phase="Fondamentali tecnici"
 elif w<=8:phase="Forza generale controllata"
 elif w<=12:phase="Mantenimento tecnico"
 else:phase="Richiamo leggero"
 if w in (4,8,12):phase="Scarico tecnico"
 if w==15:phase="Attivazione muscolare"
 return f"Forza | {phase} {minutes}'"
def exercise(eid,sets,notes,kind="Reps"):
 return {"id":eid,"sets":[{kind:v} for v in sets],"notes":notes}
def blocks(w,minutes):
 light=w in (4,8,12,14,15)
 activation=w==15
 reps=1 if light else 2
 if activation:reps=1
 squat="1" if w<=4 or w==15 else "144"
 legs=[exercise(squat,[6]*reps,"Squat senza cedimento, RPE5-6, 3-5 ripetizioni in riserva, rec 90-120s; bodyweight se non padroneggi il sovraccarico."),
       exercise("579",[8] if light else [8,8],"Ponte glutei controllato, rec 60-75s. Alternativa senza attrezzi al carico."),
       exercise("553",[8] if light else [8,8],"Calf raise controllato, rec 60-75s; niente eccentriche lente esasperate.")]
 if not activation and minutes>=35:
  legs.insert(1,exercise("154",[5] if light else [5,5],"Romanian deadlift leggero o hinge senza carico; 3-5 RIR, recupero 90-120s. Evita indolenzimento residuo."))
 upper=[exercise("516",[8] if light else [8,8],"Rematore; rec 60-75s, RPE5-6."),
        exercise("616",[8],"Push-up inclinato, versione familiare, rec 60s.")]
 core=[exercise("79",[20],"Side plank 20 secondi per lato, postura stabile; rec 30-45s",kind="Duration")]
 if minutes<25:
  legs=legs[:2]
  upper=upper[:1]
  core=[]
 warm={"type":"WarmUp","title":"Attivazione dentro la durata","notes":"5-7 minuti dentro i minuti totali; mobilità di anche e spalle senza fatica.",
       "exercises":[exercise("579",[8],"Movimento facile, preparazione tecnica."),
                    exercise("1",[8],"Squat corpo libero facile.")]}
 result=[warm]
 for i,x in enumerate(legs+upper+core,1):
  result.append({"type":"SingleExercise","title":f"Esercizio {i}","notes":x["notes"],"exercises":[x]})
 must(_validate_blocks(result) is None,"STRENGTH_BLOCK_INVALID_"+str(w))
 return result
def instructions(w,minutes):
 return (f"OBIETTIVO\\n{('Recupero attivo e mantenimento del gesto' if w in (4,8,12,15) else 'Migliorare controllo e forza generale senza interferire con il weekend')}. "
  f"Durata prevista {minutes} minuti, INCLUDE riscaldamento, pause tra serie e cambi esercizio.\\n\\n"
  "COME\\nSegui gli esercizi visibili nel Builder con movimento familiare e controllato. "
  "Recupera circa 90-120 secondi nei movimenti principali, 60-75 secondi negli accessori, 30-45 secondi nel core. "
  "Le serie e le ripetizioni nel Builder sono dosi conservative; non aggiungere volume per usare tutti i minuti. "
  "RPE muscolare orientativo 5-6 su 10, lascia 3-5 ripetizioni in riserva, niente cedimento, salti o prova del massimale. "
  "Se non hai accesso ai manubri sostituisci squat goblet con squat libero e hip hinge con ponte glutei.\\n\\n"
  "COSA OSSERVARE\\nLa forza non deve generare DOMS significativi per corsa lunga sabato e bici lunga domenica. "
  "Se questa settimana il weekend risente del lavoro mercoledì, scala una serie dei movimenti per le gambe o riduci il carico.\\n\\n"
  "RECUPERO\\nPasti regolari con sufficiente quota proteica e idratazione; adattare se sonno o recupero peggiorano.")
def dt(row):return (ANCHOR+timedelta(weeks=row["week"]-1,days=row["day"])).isoformat()
async def main():
 a=work();must(len(a)==15,"STRENGTH_MANIFEST_NOT_15")
 for r in a:must(r["day"]==2 and r["week"]<=15,"BAD_STRENGTH_DAY")
 async with TPClient() as c:
  me=await c._get_user_data();p=await c.get(f"/plans/v1/plans/{PLAN}")
  must(isinstance(me,dict) and me.get("personId")==OWNER and not p.is_error and isinstance(p.data,dict),"OWNER_OR_PLAN_READ")
  meta=p.data;person=meta.get("planPersonId")
  must(meta.get("planId")==PLAN and meta.get("title")==TITLE and meta.get("isPublic") is False and meta.get("price") in (None,0) and isinstance(person,int) and person>0,"PLAN_OWNER_SCOPE")
  must((meta.get("startDate") or "")[:10]=="2027-01-05","START_DAY_GUARD")
  n0=meta.get("workoutCount")
  must(isinstance(n0,int) and EXPECTED<=n0<=EXPECTED+15,"UNEXPECTED_WORKOUT_COUNT")
  _,token,err=await _access(c);must(not err and bool(token),"STRENGTH_AUTH_UNAVAILABLE")
  async with httpx.AsyncClient(timeout=30,follow_redirects=False) as h:
   async def read_all():
    res=await h.get(f"{STRENGTH_API_BASE}{BASE}/workouts/calendar/{person}/{ANCHOR.isoformat()}/{(ANCHOR+timedelta(days=111)).isoformat()}",headers=_headers(token))
    must(res.status_code==200 and isinstance(res.json(),list),"NATIVE_READ_FAIL_"+str(res.status_code))
    return res.json()
   current=await read_all()
   names={(dt(r),title(r["minutes"],r["week"])) for r in a}
   def key(z):return ((z.get("prescribedDate") or "")[:10],z.get("title"))
   must(all(key(v) in names for v in current),"UNRELATED_NATIVE_ON_PLAN")
   must(len(current)==len(set(key(v) for v in current)),"DUP_NATIVE")
   must(n0==EXPECTED+len(current),"PLAN_NATIVE_COUNT_MISMATCH")
   print(json.dumps({"stage":"STRENGTH_PREFLIGHT","plan":PLAN,"person":person,"already":len(current),"expected":len(a)}),flush=True)
   inserted=0
   for row in a:
    day=dt(row);w=row["week"];mins=row["minutes"];name=title(mins,w)
    match=[v for v in current if key(v)==(day,name)]
    if match:
     must(len(match)==1 and match[0].get("workoutType")=="StructuredStrength","EXISTING_NATIVE_MISMATCH")
     continue
    bs=blocks(w,mins)
    payload=_build_payload(person,day,name,bs,instructions(w,mins))
    payload["prescribedDurationInSeconds"]=mins*60
    try:res=await h.post(f"{STRENGTH_API_BASE}{BASE}/plans/{PLAN}/workouts/save",headers=_headers(token),json=payload)
    except httpx.RequestError:
     print(json.dumps({"stage":"NATIVE_POST_UNCERTAIN","week":w,"retry":False}),flush=True);return 4
    if res.status_code!=200:
     print(json.dumps({"stage":"NATIVE_WRITE_REJECTED","week":w,"http":res.status_code,"body":res.text[:320]}),flush=True);return 5
    rid=str((res.json().get("data") or {}).get("id") or payload["id"])
    check=await h.get(f"{STRENGTH_API_BASE}{BASE}/workouts/{rid}",headers=_headers(token))
    z=(check.json().get("data") or {}) if check.status_code==200 else {}
    must(z.get("title")==name and z.get("workoutType")=="StructuredStrength"
       and z.get("calendarId")==person and (z.get("prescribedDate") or "")[:10]==day
       and z.get("prescribedDurationInSeconds")==mins*60 and len(z.get("blocks") or [])==len(bs),"STRENGTH_NATIVE_POSTCHECK_"+str(w))
    n=await c.get(f"/plans/v1/plans/{PLAN}")
    must(not n.is_error and n.data.get("workoutCount")==n0+inserted+1,"STRENGTH_COUNT_MISMATCH")
    inserted+=1
    current.append(z)
    print(json.dumps({"stage":"NATIVE_VERIFIED","week":w,"id":rid,"minutes":mins,"blocks":len(bs)}),flush=True)
   final=await read_all()
   must(len(final)==15 and set(key(v) for v in final)==names,"FINAL_NATIVE_SET_FAIL")
   p=await c.get(f"/plans/v1/plans/{PLAN}")
   must(not p.is_error and p.data.get("workoutCount")==133 and p.data.get("isPublic") is False,"FULL_PLAN_COUNT_FAIL")
   print(json.dumps({"stage":"STRENGTH_15_COMPLETE","plan":PLAN,"native":15,"workouts":133,"private":True,"athlete_writes":0}),flush=True)
   return 0
if __name__=="__main__":
 try:raise SystemExit(asyncio.run(main()))
 except Exception as e:
  print(json.dumps({"stage":"STRENGTH_STOP","error":str(e),"kind":type(e).__name__}),flush=True);raise SystemExit(97)
