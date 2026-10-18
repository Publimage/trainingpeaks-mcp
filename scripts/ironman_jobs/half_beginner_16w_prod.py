"""Autonomous production of private 16-week Half Beginner plan from coach-approved week layout.
No athlete writes. Reusable shared discipline libraries, neutral template titles, verified native steps.
On each run complete one not-yet-complete four-week block (max 37 endurance workouts).
"""
import asyncio,json,re
from datetime import date,timedelta
from tp_mcp.client import TPClient
OWNER=2116886
TITLE="ALBERTO FAZI ENDURANCE | 70.3 | 16 settimane | Beginner | Italiano"
ANCHOR=date(2027,1,4)
LIB={"SW":3891872,"BI":3892601,"RU":3892602}
SPORT={"SW":(1,2),"BI":(2,3),"RU":(3,10)}
DAYS={"MA":1,"ME":2,"GI":3,"VE":4,"SA":5,"DO":6}
# Per-week schedule, in relative days. ST will be added as native Strength Builder in a separate writer.
MATRIX=[
"MA SW35 RU30 ME BI60 ST45 GI RU25 VE SW35 SA RU45 DO BI85",
"MA SW40 RU25 ME BI65 ST50 GI RU25 VE SW40 SA RU50 DO BI95",
"MA SW44 RU30 ME BI75 ST45 GI RU25 VE SW43 SA RU55 DO BI105 RU10",
"MA SW36 RU30 ME BI65 ST30 GI RU25 VE SW35 SA RU40 DO BI75",
"MA SW45 RU30 ME BI71 ST48 GI RU30 VE SW45 SA RU60 DO BI115",
"MA SW48 RU32 ME BI79 ST48 GI RU31 VE SW48 SA RU65 DO BI125 RU10",
"MA SW51 RU35 ME BI87 ST48 GI RU35 VE SW51 SA RU70 DO BI135 RU10",
"MA SW39 RU32 ME BI84 ST24 GI RU32 VE SW39 SA RU50 DO BI90",
"MA SW54 RU30 ME BI78 ST42 GI RU30 VE SW54 SA RU75 DO BI150 RU15",
"MA SW57 RU34 ME BI80 ST42 GI RU33 VE SW57 SA RU80 DO BI160 RU15",
"MA SW60 RU34 ME BI88 ST42 GI RU34 VE SW60 SA RU85 DO BI170 RU15",
"MA SW45 RU36 ME BI88 ST24 GI RU36 VE SW45 SA RU60 DO BI110",
"MA SW63 RU32 ME BI84 ST36 GI RU32 VE SW63 SA RU90 DO BI180 RU20",
"MA SW66 RU33 ME BI97 ST30 GI RU32 VE SW66 SA RU95 DO BI185 RU20",
"MA SW45 RU36 ME BI86 ST18 GI RU35 VE SW45 SA RU55 DO BI100",
"MA SW36 ME BI40 GI RU30 VE BI32 SA RU18"
]
SW_METERS=[1200,1400,1500,1300,1600,1700,1800,1550,1850,2000,2150,1700,2300,2400,1700,1200]
def fail(cond,msg):
 if not cond:raise RuntimeError(msg)
def items():
 result=[]
 for w,line in enumerate(MATRIX,1):
  day=None;count={}
  for token in line.split():
   if token in DAYS:day=token;continue
   m=re.fullmatch(r"(SW|BI|RU|ST)(\d+)",token)
   fail(m is not None and day is not None,"BAD_MATRIX")
   sp,mins=m.group(1),int(m.group(2))
   count[(day,sp)]=count.get((day,sp),0)+1
   fail(count[(day,sp)]==1,"DUP_SPORT_DAY")
   result.append({"week":w,"day":DAYS[day],"sport":sp,"minutes":mins,
                  "uid":f"AF-H703-B-{w:02d}-{day}-{sp}"})
 return result
def expected():
 rows=items()
 fail(len(rows)==133,"MANIFEST_COUNT")
 return rows
def blocks_by_time(minutes,sport,kind,week):
 if sport=="RU":
  warm=max(5,min(12,round(minutes*.18)))
  cool=max(4,min(9,round(minutes*.12)))
  main=minutes-warm-cool
  if kind=="brick":warm=0;cool=min(4,minutes//4);main=minutes-cool
  vals=[("Avvio sciolto",warm,1,2,"warmUp"),("Corsa regolare",main,2,3,"active"),("Defaticamento",cool,1,2,"coolDown")]
  if kind=="brick":vals=[("Primi passi dopo bici: tranquilli",main,2,3,"active"),("Sciolti",cool,1,2,"coolDown")]
 elif sport=="BI":
  warm=min(15,max(8,round(minutes*.15)))
  cool=min(12,max(5,round(minutes*.08)))
  main=minutes-warm-cool
  if kind=="short":
   work=min(24,max(0,main//2)) if week>=5 and week not in (8,12,15,16) else 0
   if work:
    vals=[("Riscaldamento",warm,1,2,"warmUp"),("Fondo facile",main-work,2,3,"active"),("Controllo regolare RPE3-4",work,3,4,"active"),("Ritorno facile",cool,1,2,"coolDown")]
   else:vals=[("Riscaldamento",warm,1,2,"warmUp"),("Fondo facile",main,2,3,"active"),("Ritorno facile",cool,1,2,"coolDown")]
  else:
   vals=[("Riscaldamento",warm,1,2,"warmUp"),("Lungo aerobico senza forzare",main,2,3,"active"),("Ritorno facile",cool,1,2,"coolDown")]
 else:raise RuntimeError("BAD_SPORT")
 result=[];idx=0
 for name,mi,lo,hi,cl in vals:
  if mi<=0:continue
  sec=mi*60
  result.append({"type":"step","length":{"value":1,"unit":"repetition"},"steps":[
      {"name":name,"length":{"value":sec,"unit":"second"},
       "targets":[{"minValue":lo,"maxValue":hi}],
       "intensityClass":cl,"openDuration":False}],"begin":idx,"end":idx+sec})
  idx+=sec
 fail(idx==minutes*60,"BAD_DURATION")
 return result
def swim_structure(week,which):
 meters=SW_METERS[week-1]
 warm=200;cool=100;tech=200 if meters>=1200 else 100
 middle=meters-warm-cool-tech
 fail(middle>0 and middle%50==0,"SWIM_INVARIANT")
 # Only second swim of W13/W14 includes an uninterrupted 1900m race-distance rehearsal.
 if which==2 and week>=13 and week<=14: 
  tech=meters-200-100-1900;middle=1900
  fail(tech>=0 and tech%50==0,"SWIM_REHEARSAL")
 if which==2 and week in (13,14):chunk=1900
 elif which==1:chunk=100 if week<=4 else 200 if week<=8 else 250 if week<=12 else 300
 else:chunk=200 if week<=4 else 300 if week<=8 else 400 if week<=12 else 300
 # Variable, readable intervals: keep main exact; avoid strange fractional divisions.
 if middle%chunk:chunk=100 if middle%100==0 else 50
 segs=[("Riscaldamento 200 m",warm,1,2,3,"warmUp"),
       ("Tecnica essenziale: espirazione e assetto",tech, max(1,tech//50),2,3,"active"),
       ("Crawl continuo a respirazione regolare",middle,max(1,middle//chunk),2,4,"active"),
       ("Defaticamento 100 m",cool,1,1,2,"coolDown")]
 result=[];at=0
 for title,dist,reps,lo,hi,cl in segs:
  if dist==0:continue
  fail(dist%reps==0,"BAD_SWIM_STEP")
  result.append({"type":"repetition" if reps>1 else "step",
     "length":{"value":reps,"unit":"repetition"},
     "steps":[{"name":title,"length":{"value":dist//reps,"unit":"meter"},
        "targets":[{"minValue":lo,"maxValue":hi}],
        "intensityClass":cl,"openDuration":False}],"begin":at,"end":at+dist})
  at+=dist
 fail(at==meters,"SWIM_SUM")
 return {"structure":result,"primaryLengthMetric":"distance","visualizationDistanceUnit":"meter",
         "primaryIntensityMetric":"rpe","primaryIntensityTargetOrRange":"range"}
def make(row):
 w,d,sp,minutes=row["week"],row["day"],row["sport"],row["minutes"]
 fail(sp in LIB,"STRENGTH_OWNED_BY_NATIVE_PATH")
 recovery=w in (4,8,12,15)
 race=w==16
 if sp=="SW":
  which=1 if d==1 else 2
  total=SW_METERS[w-1]
  title=f"{'Tecnica' if which==1 else 'Aerobico'} | Crawl {'assetto e respiro' if which==1 else 'regolare'} {total} m"
  structure=swim_structure(w,which)
  full=sum((b["length"]["value"] if b["type"]=="repetition" else 1)*sum(s["length"]["value"] for s in b["steps"]) for b in structure["structure"])
  fail(full==total,"SWIM_VOLUME_MISMATCH")
  description=(f"OBIETTIVO\\n{('Economia del crawl e respirazione senza affaticamento' if which==1 else 'Sostenere tratte progressivamente più lunghe con nuotata regolare')}. "
     f"Distanza prescritta {total}m; durata organizzativa circa {minutes} min, comprensiva di pause.\\n\\n"
     "COME\\nSegui la struttura a metri. Nei 50m di tecnica cura espirazione continua sott'acqua, assetto e traiettoria: niente attrezzi obbligatori. "
     "Tra le ripetizioni recupera 15-30 secondi o finché la respirazione torna regolare, senza cercare di comprimere le pause. "
     "RPE 2-3 nelle frazioni facili, fino a 4 soltanto quando la nuotata resta controllata.\\n\\n"
     "COSA OSSERVARE\\nControlla se la seconda metà del lavoro mantiene ampiezza, orientamento e respirazione simili alla prima. "
     "Non ricavare automaticamente CSS o soglia dai soli dati di questa seduta.\\n\\n"
     "ADATTAMENTO\\nSe perdi coordinazione, riduci la lunghezza della ripetuta mantenendo i metri complessivi soltanto se tecnicamente sicuro; "
     "in caso di affaticamento inconsueto termina la seduta. Acque libere soltanto in condizioni sicure, mai da soli.\\n"
     +( "PROVA DISTANZA GARA\\nLa frazione continua di 1900m non è un test massimale: misura sicurezza e sostenibilità del gesto.\\n" if which==2 and w in(13,14) else ""))
  return (title,description,structure,total)
 kind="brick" if sp=="RU" and d==6 else "long" if d in (5,6) else "short"
 if race:kind="activation"
 if sp=="RU":
  label="Brick | Corsa di transizione" if kind=="brick" else "Lungo | Corsa facile" if kind=="long" else "Attivazione | Corsa agile" if race else "Aerobico | Corsa conversazionale"
  title=f"{label} {minutes}'"
  structure={"structure":blocks_by_time(minutes,sp,"brick" if kind=="brick" else "normal",w),
     "primaryLengthMetric":"duration","primaryIntensityMetric":"rpe",
     "primaryIntensityTargetOrRange":"range"}
  desc=("OBIETTIVO\\n"+("Assorbire la transizione dalla bici senza inseguire il passo." if kind=="brick" else
       "Consolidare durata di corsa facile minimizzando lo stress muscolo-tendineo." if kind=="long" else
       "Contatto regolare con la corsa, in forma conversazionale.")+
       "\\n\\nESECUZIONE\\nUsa i blocchi del Builder. RPE 2-3 per quasi tutta la seduta, puoi parlare in frasi complete. "
       "Se hai una soglia di corsa validata usa il ritmo come controllo secondario, non forzare percentuali non calibrate. "
       "Evita ripetute aggiunte.\\n\\nRECUPERO\\nValuta dolore muscolo-tendineo, rigidità, sonno, andatura e respiro. "
       "Se compare dolore che altera il gesto, interrompi. Se la corsa del sabato causa pesantezza insolita, domenica la bici deve essere più facile e il brick va saltato.\\n"
       +("FUELING\\nSe superi 75-90min usa un'opzione già tollerata per acqua e carboidrati; controlla caldo e durata, non sperimentare il giorno della gara.\\n" if minutes>=75 else ""))
  return(title,desc,structure,None)
 label=("Attivazione | Bici agile" if race else
        "Lungo | Bici aerobica" if kind=="long" else "Aerobico | Bici controllo e cadenza")
 title=f"{label} {minutes}'"
 structure={"structure":blocks_by_time(minutes,sp,"long" if kind=="long" else "short",w),
       "primaryLengthMetric":"duration","primaryIntensityMetric":"rpe",
       "primaryIntensityTargetOrRange":"range"}
 desc=("OBIETTIVO\\n"+("Preparare resistenza e gestione energetica senza accumulare affaticamento eccessivo." if kind=="long" else
     "Tenere una seduta distinta dal lungo: posizione, fluidità e controllo aerobico.")+
     "\\n\\nESECUZIONE\\nSegui i blocchi a RPE sul Builder: per le porzioni facili RPE2-3, quando indicato controllo regolare RPE3-4, "
     "senza pedalare a soglia. Se possiedi FTP recente e affidabile, osserva potenza e frequenza cardiaca come conferma, "
     "ma FTP non equivale direttamente a LT1 o LT2 e non sono prescritti watt universali. "
     "Cerca cadenza spontanea e postura sostenibile; non inseguire watt in salita.\\n\\n"
     "COSA OSSERVARE\\nVerifica stabilità di respirazione e capacità di mantenere l'output con costo interno contenuto. "
     "Annota sensazioni verso il finale e recupero del giorno dopo.\\n"
     +( "ALIMENTAZIONE\\nOltre circa 90 minuti prova gradualmente 30-60g di carboidrati all'ora, aumentando solo in base a tolleranza e durata; acqua e sodio secondo sudorazione e condizioni. Testa gli stessi prodotti prima della gara.\\n" if minutes>=90 else
        "ALIMENTAZIONE\\nAcqua secondo sete e condizioni, alimentazione ordinaria per durata breve.\\n"))
 return(title,desc,structure,None)
def structure_len(ss):
 z=0
 for b in ss["structure"]:
  n=b["length"]["value"] if b["type"]=="repetition" else 1
  z+=n*sum(s["length"]["value"] for s in b["steps"])
 return z
async def main():
 rows=expected()
 async with TPClient() as c:
  me=await c._get_user_data();fail(isinstance(me,dict) and me.get("personId")==OWNER,"OWNER_MISMATCH")
  listing=await c.get("/plans/v1/plans");fail(not listing.is_error and isinstance(listing.data,list),"PLAN_LIST_FAIL")
  matches=[x for x in listing.data if x.get("title")==TITLE]
  fail(len(matches)<=1,"DUPLICATE_PLAN_TITLE")
  if not matches:
   r=await c._request("POST","/plans/v1/plans",json={"title":TITLE,"startDate":ANCHOR.isoformat()+"T00:00:00","weekCount":16,"dayCount":112,"isPublic":False,
      "description":"Piano 16 settimane per completare il primo 70.3; stato privato in produzione, NON in vendita. Valutare requisiti di ingresso, idoneità e progressione."},_retry_on_401=False)
   if r.is_error:
    print(json.dumps({"stage":"CREATE_RESULT_UNKNOWN_CHECK_PLAN_LIST","error":str(r.error_code)}),flush=True);return 3
   listing=await c.get("/plans/v1/plans")
   fail(not listing.is_error and isinstance(listing.data,list),"PLAN_CREATE_READBACK_FAIL")
   matches=[x for x in listing.data if x.get("title")==TITLE]
   fail(len(matches)==1,"PLAN_CREATE_UNVERIFIED")
  plan=matches[0].get("planId")
  detail=await c.get(f"/plans/v1/plans/{plan}")
  fail(not detail.is_error and isinstance(detail.data,dict),"PLAN_DETAIL_MISSING")
  pd=detail.data
  fail(pd.get("title")==TITLE and pd.get("planId")==plan and pd.get("isPublic") is False and pd.get("price") in (None,0),"PLAN_SCOPE_GUARD")
  fail((pd.get("startDate") or "")[:10] in (ANCHOR.isoformat(),(ANCHOR+timedelta(days=1)).isoformat()),"ANCHOR_CHANGED")
  sources={}
  for sp,lid in LIB.items():
   r=await c.get(f"/exerciselibrary/v2/libraries/{lid}/items")
   fail(not r.is_error and isinstance(r.data,list),"LIBRARY_READ_"+sp)
   sources[sp]={x["itemName"]:x for x in r.data}
  async def read_calendar():
   r=await c.get(f"/plans/v1/plans/{plan}/workouts/{ANCHOR.isoformat()}/{(ANCHOR+timedelta(days=112)).isoformat()}")
   fail(not r.is_error and isinstance(r.data,list),"PLAN_CALENDAR_READ_FAIL")
   return r.data
  old=await read_calendar()
  def plan_day(r):return (ANCHOR+timedelta(weeks=r["week"]-1,days=r["day"])).isoformat()
  exp_nonst=[r for r in rows if r["sport"]!="ST"]
  allowed={(plan_day(r),r["sport"]) for r in exp_nonst}
  existing_by_day={}
  for v in old:
   sp={1:"SW",2:"BI",3:"RU",6:"ST"}.get(v.get("workoutTypeValueId"))
   if sp=="ST":continue
   dt=(v.get("workoutDay") or "")[:10]
   fail((dt,sp) in allowed,"UNKNOWN_PLAN_WORKOUT_"+str((dt,sp)))
   existing_by_day.setdefault((dt,sp),[]).append(v)
  fail(all(len(z)==1 for z in existing_by_day.values()),"DUPLICATE_PLAN_SLOT")
  # The first four-week block that is not yet complete. Do not overwrite other blocks.
  target_blocks=[(1,4),(5,8),(9,12),(13,16)]
  chosen=None
  for lo,hi in target_blocks:
   want=[r for r in exp_nonst if lo<=r["week"]<=hi]
   if any((plan_day(r),r["sport"]) not in existing_by_day for r in want):
    chosen=(lo,hi,want);break
  if chosen is None:
   print(json.dumps({"stage":"ENDURANCE_118_COMPLETE","plan_id":plan,"found":len(existing_by_day)}));return 0
  lo,hi,want=chosen
  print(json.dumps({"stage":"PREFLIGHT_PASS","plan_id":plan,"block":[lo,hi],"existing_nonstrength":len(existing_by_day),"to_fill":sum((plan_day(r),r["sport"]) not in existing_by_day for r in want)}),flush=True)
  created=0;copied=0;already=0
  for row in want:
   dt=plan_day(row);sp=row["sport"];minutes=row["minutes"];title,desc,struct,meters=make(row)
   fail(not re.search(r"70\.3|\bW\d\d\b",title,re.I),"PUBLIC_TITLE_HAS_CODE")
   fail(structure_len(struct)==(meters if sp=="SW" else minutes*60),"STRUCTURE_TOTAL")
   key=(dt,sp)
   if key in existing_by_day:
    v=existing_by_day[key]
    fail(len(v)==1 and v[0].get("title")==title and v[0].get("description")==desc and abs((v[0].get("totalTimePlanned") or 0)*60-minutes)<.1,"EXISTING_SLOT_MISMATCH")
    already+=1;continue
   source=sources[sp].get(title)
   if source:
    fail(abs((source.get("totalTimePlanned") or 0)*60-minutes)<.1 and source.get("description")==desc and bool(source.get("structure")),"EXISTING_TEMPLATE_MISMATCH")
    iid=source["exerciseLibraryItemId"]
   else:
    lid=LIB[sp];fam,sub=SPORT[sp]
    payload={"exerciseLibraryId":lid,"itemName":title,"workoutTypeId":fam,"workoutSubTypeId":sub,
      "totalTimePlanned":minutes/60,"description":desc}
    if meters:payload["distancePlanned"]=meters
    create=await c._request("POST",f"/exerciselibrary/v1/libraries/{lid}/items",json=payload,_retry_on_401=False)
    if create.is_error:
     print(json.dumps({"stage":"TEMPLATE_POST_UNCERTAIN","title":title,"week":row["week"],"error":str(create.error_code)}),flush=True);return 4
    r=await c.get(f"/exerciselibrary/v2/libraries/{lid}/items")
    fail(not r.is_error and isinstance(r.data,list),"LIB_ITEM_RECHECK")
    item=[v for v in r.data if v.get("itemName")==title]
    fail(len(item)==1,"TEMPLATE_CREATE_AMBIGUITY")
    src=item[0];iid=src["exerciseLibraryItemId"]
    upd=dict(src)
    upd["structure"]=struct
    # v1 update is confirmed route: use full native shape with existing id.
    saved=await c._request("PUT",f"/exerciselibrary/v1/libraries/{lid}/items/{iid}",json=upd,_retry_on_401=False)
    if saved.is_error:
     print(json.dumps({"stage":"TEMPLATE_STRUCTURE_WRITE_UNKNOWN","item":iid,"week":row["week"]}),flush=True);return 5
    rr=await c.get(f"/exerciselibrary/v2/libraries/{lid}/items")
    fail(not rr.is_error and isinstance(rr.data,list),"TEMPLATE_VERIFY_UNAVAILABLE")
    verified=[x for x in rr.data if x.get("exerciseLibraryItemId")==iid]
    fail(len(verified)==1 and isinstance(verified[0].get("structure"),dict)
         and structure_len(verified[0]["structure"])==structure_len(struct),"TEMPLATE_STRUCTURE_FAILED")
    sources[sp][title]=verified[0];created+=1
   posted=await c._request("POST",f"/plans/v1/plans/{plan}/commands/addworkoutfromlibraryitem",
     json={"planId":plan,"exerciseLibraryItemId":iid,"workoutDateTime":dt},_retry_on_401=False)
   if posted.is_error:
    print(json.dumps({"stage":"PLAN_COPY_POST_UNKNOWN","item":iid,"date":dt,"week":row["week"]}),flush=True);return 6
   now=await read_calendar()
   matches=[v for v in now if (v.get("workoutDay") or "")[:10]==dt and v.get("title")==title
            and v.get("workoutTypeValueId")==SPORT[sp][0]]
   fail(len(matches)==1 and matches[0].get("description")==desc and
        abs((matches[0].get("totalTimePlanned") or 0)*60-minutes)<.1,"COPIED_WORKOUT_QA_FAIL")
   existing_by_day[key]=matches;copied+=1
  now=await read_calendar()
  summary={"stage":"BLOCK_DONE","plan_id":plan,"block":[lo,hi],"new_templates":created,
   "copied":copied,"already":already,"total_classic":len(now),"private":True,"athlete_writes":0}
  print(json.dumps(summary,ensure_ascii=False),flush=True)
  return 0
if __name__=="__main__":
 raise SystemExit(asyncio.run(main()))
