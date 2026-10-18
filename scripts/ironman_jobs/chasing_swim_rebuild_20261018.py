"""CHASING 685173 — full Swim rebuild, 2026-10-18.
Replaces exactly 71 existing plan Swim occurrences in place.
No Bike/Run/Strength/Note/PDF/athlete-calendar/library writes.
Design gate includes real functional variety and continuous 3.5/3.8/4.0 km exposures.
"""
import asyncio, copy, hashlib, json, math
from datetime import date
from pathlib import Path
from tp_mcp.client import TPClient
from tp_mcp.tools.library import _ensure_structure_preview

PLAN=685173
OWNER=2116886
PERSON=6682479
START=date(2027,1,4)
RANGES=(("2027-01-04","2027-02-28"),("2027-03-01","2027-04-25"),("2027-04-26","2027-06-20"))
BACKUP=Path.home()/".trainingpeaks-mcp/chasing_swim_rebuild_20261018_backup.json"

IDS={
1:[4000486945,4000490051,4000490159],
2:[4000490220,4000490258,4000490371],
3:[4000591453,4000591488,4000591562],
4:[4000591594,4000591617,4000591658],
5:[4000954198,4000954221,4000954283],
6:[4000966381,4000966419,4000966552],
7:[4000972865,4000972939,4000973018],
8:[4001046288,4001046327,4001046400],
9:[4001048374,4001048397,4001048469],
10:[4001050241,4001050262,4001050317],
11:[4001052931,4001052958,4001053036],
12:[4001055493,4001055532,4001055602],
13:[4001058868,4001058996,4001059157],
14:[4001062008,4001062141,4001062246],
15:[4001065266,4001065316,4001065380],
16:[4001068996,4001069057,4001069153],
17:[4001071935,4001071969,4001072040],
18:[4001074454,4001074478,4001074531],
19:[4001076744,4001076798,4001076910],
20:[4001078695,4001078749,4001078837],
21:[4001080942,4001080978,4001081142],
22:[4001083421,4001083483,4001083654],
23:[4001086333,4001086460,4001086507],
24:[4001089818,4001089870],
}

# kind, total metres, planned minutes, continuous-main metres when applicable
CFG={
1:[("test",2500,50,1500),("tech",2600,55,0),("cont",2800,60,2200)],
2:[("tech",2900,60,0),("q100",3000,60,0),("cont",3000,65,2400)],
3:[("q200",3100,65,0),("cont",3200,65,2600),("tech",3000,60,0)],
4:[("tech_easy",2400,50,0),("aero",2500,50,0),("cont",2600,55,2000)],
5:[("tech",3200,65,0),("test",2500,50,1500),("cont",3300,65,2800)],
6:[("cont",3400,70,2800),("q200",3300,65,0),("tech",3200,65,0)],
7:[("q100",3400,65,0),("tech",3300,65,0),("cont",3500,70,3000)],
8:[("tech_easy",2700,55,0),("cont",2800,60,2200),("aero",2700,55,0)],
9:[("tech",3400,65,0),("test",2500,50,1500),("cont",3600,70,3000)],
10:[("cont",3700,70,3100),("q200",3600,70,0),("tech",3500,65,0)],
11:[("q400",3700,70,0),("cont",3800,75,3200),("tech",3600,70,0)],
12:[("tech_easy",2900,55,0),("aero",3000,60,0),("cont",3100,60,2500)],
13:[("q200",3800,75,0),("tech",3700,70,0),("cont",3900,75,3300)],
14:[("tech",3800,70,0),("cont",4000,75,3500),("q400",3900,75,0)],
15:[("q100",3300,60,0),("tech",3300,60,0),("cont",3500,60,3500)],
16:[("tech_easy",3000,60,0),("cont",3200,60,2600),("aero",3100,60,0)],
17:[("cont",4200,80,3700),("q200",4000,75,0),("tech",3900,70,0)],
18:[("tech",4000,75,0),("q400",4100,75,0),("cont",4200,80,3800)],
19:[("q100",4200,80,0),("tech",4000,75,0),("cont",4000,80,4000)],
20:[("tech_easy",3300,65,0),("cont",3400,65,2800),("aero",3500,70,0)],
21:[("q200",3300,60,0),("cont",3500,60,3500),("tech",3300,60,0)],
22:[("tech",3600,70,0),("q100",3600,70,0),("cont",3500,70,3000)],
23:[("tech_easy",2700,55,0),("cont",2800,55,2200),("activation",2400,45,0)],
24:[("activation",1800,35,0),("activation2",1400,30,0)],
}

PHASE={
1:"calibrazione",2:"base",3:"base",4:"assorbimento",
5:"sviluppo",6:"sviluppo",7:"sviluppo",8:"assorbimento",
9:"sviluppo specifico",10:"sviluppo specifico",11:"sviluppo specifico",12:"assorbimento",
13:"specificità",14:"specificità",15:"specificità",16:"assorbimento",
17:"specificità avanzata",18:"specificità avanzata",19:"rehearsal",20:"assorbimento",
21:"consolidamento",22:"taper",23:"taper",24:"race week"
}

def need(v,msg):
    if not v: raise RuntimeError(msg)

def digest(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,default=str,ensure_ascii=False).encode()).hexdigest()

def stable(v):
    return {k:x for k,x in v.items() if k!="lastModifiedDate"}

def week_of(w):
    d=date.fromisoformat(str(w.get("workoutDay") or "")[:10])
    return (d-START).days//7+1

def _group(count,metres,name,rpe=(2,3),klass="active",recovery=0):
    return {"count":count,"metres":metres,"name":name,"rpe":rpe,"klass":klass,"recovery":recovery}

def _fill(groups, remaining, week, label="Nuoto completo aerobico", rpe=(3,4)):
    need(remaining>=0 and remaining%50==0,"INVALID_FILL_"+str(remaining))
    if remaining==0: return
    choices=[300,250,200,150,100]
    choices=choices[week%len(choices):]+choices[:week%len(choices)]
    for unit in choices:
        if remaining%unit==0 and 2<=remaining//unit<=8:
            groups.append(_group(remaining//unit,unit,label,rpe,"active",20 if unit<=200 else 25))
            return
    if remaining>=800:
        first=(remaining//200//2)*200
        if first<400:first=400
        second=remaining-first
        if second>=200 and second%50==0:
            groups.append(_group(1,first,label+" — blocco 1",rpe,"active",30))
            groups.append(_group(1,second,label+" — blocco 2",rpe,"active",0))
            return
    groups.append(_group(1,remaining,label,rpe,"active",0))

def build_groups(week,kind,total,main):
    g=[]
    if kind=="test":
        g=[_group(1,400,"Riscaldamento", (2,3),"warmUp"),
           _group(4,50,"Build controllato",(4,6),"active",15),
           _group(1,200,"Facile",(2,3),"active"),
           _group(1,1500,"T1500",(9,10),"active"),
           _group(1,200,"Defaticamento",(1,2),"coolDown")]
    elif kind=="cont":
        if main==total:
            g=[_group(1,total,"Nuoto continuo no-stop",(3,4),"active")]
        else:
            extra=total-main
            warm=300 if extra>=500 else 200
            cool=extra-warm
            need(cool>=100,"CONT_EXTRA_TOO_SMALL")
            g=[_group(1,warm,"Ingresso facile",(2,3),"warmUp"),
               _group(1,main,"Continuo senza pause — assetto e pacing Ironman",(3,4),"active"),
               _group(1,cool,"Sciolti",(1,2),"coolDown")]
    elif kind in ("tech","tech_easy"):
        v=week%6
        if kind=="tech_easy":
            g=[_group(1,300,"Avvio facile",(2,3),"warmUp"),
               _group(6,50,"Tecnica: 25 sculling + 25 nuoto completo",(2,3),"active",15),
               _group(4,200,"Pull buoy facile, presa lunga",(2,3),"active",20)]
            _fill(g,total-sum(x["count"]*x["metres"] for x in g),week,"Nuoto completo facile",(2,3))
        elif v==0:
            g=[_group(1,400,"Avvio progressivo",(2,3),"warmUp"),
               _group(6,50,"Tecnica: pugni chiusi / completo",(2,3),"active",15),
               _group(6,150,"Pull buoy + palette piccole, presa solida",(3,4),"active",20)]
            _fill(g,total-1600,week,"Nuoto completo fluido",(3,4))
        elif v==1:
            g=[_group(1,400,"Avvio progressivo",(2,3),"warmUp"),
               _group(8,50,"Pinne: assetto, linea e ritmo gambe leggero",(2,3),"active",15),
               _group(5,200,"Pull buoy + palette piccole, forza specifica controllata",(3,4),"active",25)]
            _fill(g,total-1800,week,"Nuoto completo con presa stabile",(3,4))
        elif v==2:
            g=[_group(1,400,"Avvio facile",(2,3),"warmUp"),
               _group(4,50,"Sculling frontale + completo",(2,3),"active",15),
               _group(4,250,"Pull buoy, controllo asse",(3,4),"active",25),
               _group(8,50,"Palette piccole senza pull, frequenza controllata",(4,5),"active",15)]
            _fill(g,total-2000,week,"Completo facile",(3,4))
        elif v==3:
            g=[_group(1,300,"Avvio facile",(2,3),"warmUp"),
               _group(6,50,"25 pugni chiusi + 25 completo",(2,3),"active",15),
               _group(8,100,"Pull buoy + palette piccole",(3,4),"active",20),
               _group(4,150,"Completo progressivo",(3,5),"active",20)]
            _fill(g,total-2000,week,"Completo aerobico",(3,4))
        elif v==4:
            g=[_group(1,400,"Avvio progressivo",(2,3),"warmUp"),
               _group(4,50,"Pinne: allineamento e rotazione",(2,3),"active",15),
               _group(5,200,"Pull buoy, pressione costante sull'acqua",(3,4),"active",20),
               _group(4,100,"Palette piccole, tecnica sotto carico",(4,5),"active",20)]
            _fill(g,total-2000,week,"Completo rilassato",(3,4))
        else:
            g=[_group(1,400,"Avvio facile",(2,3),"warmUp"),
               _group(6,50,"Sculling + completo",(2,3),"active",15),
               _group(3,300,"Pull buoy + palette piccole, forza resistente",(3,4),"active",30)]
            _fill(g,total-1600,week,"Completo lungo e uniforme",(3,4))
    elif kind in ("q100","q200","q400"):
        g=[_group(1,400,"Riscaldamento progressivo",(2,3),"warmUp"),
           _group(4,50,"Build 50: chiudi brillante ma pulito",(4,6),"active",15)]
        if kind=="q100":
            g += [_group(12,100,"100 m controllo CSS / ritmo forte sostenibile",(5,6),"active",15),
                  _group(6,50,"50 m cambio ritmo: forte controllato",(6,7),"active",20)]
        elif kind=="q200":
            g += [_group(6,200,"200 m steady-CSS controllato",(5,6),"active",20),
                  _group(4,100,"100 m progressivi, ultimo 25 brillante",(5,7),"active",20)]
        else:
            g += [_group(4,400,"400 m ritmo sostenuto uniforme",(4,6),"active",30),
                  _group(8,50,"50 m frequenza alta con tecnica pulita",(6,7),"active",20)]
        used=sum(x["count"]*x["metres"] for x in g)
        _fill(g,total-used,week,"Endurance completo di consolidamento",(3,4))
    elif kind=="aero":
        g=[_group(1,400,"Avvio facile",(2,3),"warmUp"),
           _group(4,50,"Tecnica presa/respirazione",(2,3),"active",15),
           _group(6,200,"Aerobico uniforme",(3,4),"active",20),
           _group(6,100,"100 m negative split leggero",(3,5),"active",15)]
        _fill(g,total-2400,week,"Completo facile, economia",(2,3))
    elif kind in ("activation","activation2"):
        if kind=="activation":
            g=[_group(1,300,"Ingresso facile",(1,2),"warmUp"),
               _group(6,50,"Tecnica e respirazione",(2,3),"active",15),
               _group(8,100,"100 m sciolti con 25 m ritmo gara ogni due",(2,4),"active",15)]
            _fill(g,total-1400,week,"Completo facile",(2,3))
        else:
            g=[_group(1,200,"Ingresso facile",(1,2),"warmUp"),
               _group(4,50,"Tecnica respirazione/assetto",(2,3),"active",15),
               _group(6,100,"100 m sciolti, due con breve accento",(2,4),"active",20)]
            _fill(g,total-1000,week,"Sciolto completo",(1,3))
    else:
        raise RuntimeError("UNKNOWN_KIND_"+kind)
    need(sum(x["count"]*x["metres"] for x in g)==total,
         f"METRES_MISMATCH_W{week}_{kind}_{sum(x['count']*x['metres'] for x in g)}_{total}")
    return g

def title_for(week,kind,total,main,groups,test_index=0):
    if kind=="test":
        if week==1:return "Test | T1500 iniziale - 2500 m"
        return f"Test | RETEST W{week:02d} | T1500 - 2500 m"
    if kind=="cont":
        if main==total:return f"Specifico | {main} m continuati no-stop - rehearsal"
        return f"Continuo | {main} m no-stop, pacing Ironman - {total} m"
    if kind in ("tech","tech_easy"):
        key=next((x["name"] for x in groups if "Pull" in x["name"] or "Palette" in x["name"] or "Pinne" in x["name"]),groups[1]["name"])
        short=key.split(",")[0]
        return f"Tecnica/forza | {short} - {total} m"
    if kind=="q100":return f"Qualità | 12x100 + 6x50 cambi ritmo - {total} m"
    if kind=="q200":return f"Qualità | 6x200 + 4x100 progressivi - {total} m"
    if kind=="q400":return f"Qualità | 4x400 + 8x50 frequenza - {total} m"
    if kind=="aero":return f"Aerobico | 6x200 + 6x100 negative split - {total} m"
    if kind=="activation":return f"Attivazione | tecnica + 8x100 controllo - {total} m"
    return f"Attivazione | sciolto + richiami brevi - {total} m"

def structure_for(groups):
    cursor=0; blocks=[]
    for x in groups:
        distance=x["count"]*x["metres"]
        block={
          "type":"step" if x["count"]==1 else "repetition",
          "length":{"value":1 if x["count"]==1 else x["count"],"unit":"repetition"},
          "steps":[{
             "name":x["name"],
             "length":{"value":x["metres"],"unit":"meter"},
             "targets":[{"minValue":x["rpe"][0],"maxValue":x["rpe"][1]}],
             "intensityClass":x["klass"],
             "openDuration":False
          }],
          "begin":cursor,"end":cursor+distance
        }
        blocks.append(block);cursor+=distance
    s={"structure":blocks,"primaryLengthMetric":"distance",
       "visualizationDistanceUnit":"meter",
       "primaryIntensityMetric":"rpe","primaryIntensityTargetOrRange":"range"}
    return _ensure_structure_preview(s)

def equipment_for(week,kind):
    if kind in ("tech","tech_easy"):
        if week%6 in (1,4):return "Pull buoy, palette piccole e pinne sono parte prescritta dei blocchi indicati. Se le palette alterano la presa o compare fastidio alla spalla, toglile e completa lo stesso metraggio senza palette."
        return "Pull buoy e palette piccole sono parte prescritta dei blocchi indicati. Usa palette che non costringano ad aumentare artificialmente la forza; in caso di fastidio alla spalla completa senza palette."
    if kind.startswith("q"):
        return "Main set a nuoto completo. Nessun attrezzo nel lavoro di qualità; eventuali pinne compaiono solo se esplicitamente indicate nell'attivazione."
    if kind=="cont":
        return "Nessun attrezzo nel tratto continuato: nuoto completo, assetto e respirazione da gara."
    if kind=="aero":
        return "Nessun attrezzo obbligatorio nel main set; priorità alla qualità del nuoto completo."
    if kind=="test":
        return "Nessun attrezzo nel T1500: condizioni il più possibile replicabili fra test e retest."
    return "Nessun attrezzo necessario."

def objective_for(week,kind,main):
    phase=PHASE[week]
    if kind=="test":return f"Benchmark T1500 in fase di {phase}: ottenere un riferimento comparabile senza trasformare la settimana in una batteria di test."
    if kind=="cont":
        if main>=3500:return f"Specificità full-distance in fase di {phase}: sostenere {main} m realmente continuati, senza recuperi, con tecnica e costo interno stabili."
        return f"Costruire continuità aerobica in fase di {phase}: {main} m senza pause con assetto e pacing controllati."
    if kind in ("tech","tech_easy"):return f"Economia e forza specifica in acqua in fase di {phase}: trasferire presa, assetto e controllo al nuoto completo."
    if kind.startswith("q"):return f"Qualità nuoto in fase di {phase}: variare lunghezza delle ripetute e ritmo senza perdere tecnica."
    if kind=="aero":return f"Assorbire il carico in fase di {phase} mantenendo economia, ritmo aerobico e negative split controllato."
    return f"Attivazione in fase di {phase}: mantenere sensibilità, respirazione e familiarità con il ritmo senza creare fatica."

def description_for(week,kind,total,minutes,main,groups):
    lines=["OBIETTIVO",objective_for(week,kind,main),"","STRUTTURA"]
    for x in groups:
        if x["count"]==1:
            txt=f'{x["metres"]} m — {x["name"]}'
        else:
            txt=f'{x["count"]}x{x["metres"]} m — {x["name"]}'
        if x["recovery"] and x["count"]>1:txt+=f'; rec. {x["recovery"]}"'
        if kind=="cont" and "Continuo senza pause" in x["name"]:txt+="; NESSUN recupero nel blocco"
        lines.append(txt+".")
    if kind=="cont" and main==total:
        lines += ["","CONTINUO SPECIFICO",
                  f"{total} m dall'inizio alla fine senza fermarsi. Primi 400–500 m volutamente facili; parte centrale uniforme; ultimi 800–1000 m solo leggermente progressivi se tecnica, respirazione e RPE restano controllati."]
    elif kind=="cont":
        lines += ["","CONTINUO SPECIFICO",
                  f"Il blocco da {main} m è realmente continuo: nessuna pausa, nessun 4x/2x mascherato. Partenza prudente, seconda metà uguale o lievemente più veloce solo se il gesto resta pulito."]
    lines += ["","INTENSITÀ",
              "RPE indicata nei blocchi. CSS/Swim Threshold individuale può aiutare a leggere il ritmo, ma non sostituisce tecnica, respirazione e controllo del costo interno.",
              "","ATTREZZI",equipment_for(week,kind),
              "","DURATA",f"{total} m effettivi. Planned Duration TrainingPeaks: circa {minutes}' come stima di calendario, non tempo limite universale.",
              "","FUELING"]
    if minutes>=70:
        lines.append("Arriva alimentato e ben idratato. Per sedute lunghe o molto dense tieni una borraccia a bordo vasca; se sei lontano dai pasti o la seduta supera circa 70', una piccola quota di carboidrati già tollerata può essere utile. Nessun prodotto nuovo nei rehearsal.")
    else:
        lines.append("Alimentazione abituale e buona idratazione. Se il pasto è lontano, piccolo top-up di carboidrati prima; acqua secondo sete e condizioni.")
    lines += ["","NOTE",
              f"Settimana {week}, fase {PHASE[week]}. La funzione di questa seduta è distinta dagli altri due nuoti della settimana; non trasformarla automaticamente nel workout della settimana precedente."]
    return "\n".join(lines)

def build_specs():
    specs=[]
    for week in range(1,25):
        need(len(IDS[week])==len(CFG[week]),"ID_CFG_LEN_W"+str(week))
        for slot,(wid,cfg) in enumerate(zip(IDS[week],CFG[week]),1):
            kind,total,minutes,main=cfg
            groups=build_groups(week,kind,total,main)
            specs.append({"id":wid,"week":week,"slot":slot,"kind":kind,"metres":total,
              "minutes":minutes,"main":main,"groups":groups,
              "title":title_for(week,kind,total,main,groups),
              "description":description_for(week,kind,total,minutes,main,groups)})
    return specs

def design_gate(specs):
    need(len(specs)==71 and len({x["id"] for x in specs})==71,"NOT_71_UNIQUE")
    need(all(x["metres"]>0 and x["minutes"]>0 for x in specs),"ZERO_DISTANCE_OR_DURATION")
    week_counts={w:sum(x["week"]==w for x in specs) for w in range(1,25)}
    need(all(week_counts[w]==3 for w in range(1,24)) and week_counts[24]==2,"WEEK_COUNTS")
    cont=[x for x in specs if x["kind"]=="cont"]
    mains=[x["main"] for x in cont]
    need(any(v>=3500 for v in mains) and any(v>=3800 for v in mains) and 4000 in mains,
         "CONTINUOUS_3500_3800_4000_GATE")
    need(sum(v>=3000 for v in mains)>=10,"TOO_FEW_LONG_CONTINUOUS")
    need(any(x["main"]==x["metres"]==4000 for x in cont),"NO_TRUE_4000_NO_STOP")
    desc="\n".join(x["description"].lower() for x in specs)
    need(desc.count("palette")>=10 and desc.count("pull buoy")>=10 and desc.count("pinne")>=6,
         "EQUIPMENT_VARIETY_GATE")
    need(all(any(token in desc for token in [token]) for token in ("50 m","100 m","200 m","400 m")),
         "INTERVAL_VARIETY_GATE")
    # Native structure signatures: duplicates are allowed only for standardized T1500 test/retest.
    sigs={}
    for x in specs:
        s=structure_for(x["groups"])
        sig=digest({k:v for k,v in s.items() if k!="polyline"})
        sigs.setdefault(sig,[]).append(x)
    bad=[]
    for arr in sigs.values():
        if len(arr)>1 and not all(x["kind"]=="test" for x in arr):bad.append([(x["week"],x["kind"]) for x in arr])
    need(not bad,"UNJUSTIFIED_DUPLICATE_STRUCTURES_"+str(bad))
    return {"continuous_sessions":len(cont),"long_continuous_3k_plus":sum(v>=3000 for v in mains),
      "continuous_max":max(mains),"whole_4000":sum(x["main"]==x["metres"]==4000 for x in cont)}

async def read_all(c):
    rows=[]; notes=[]
    for a,b in RANGES:
        r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{a}/{b}")
        n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{a}/{b}")
        need(not r.is_error and not n.is_error and isinstance(r.data,list) and isinstance(n.data,list),"READ_FAILED")
        rows.extend(r.data);notes.append(digest(n.data))
    need(len(rows)==249 and len({x["workoutId"] for x in rows})==249,"TRADITIONAL_249_DRIFT")
    return rows,notes

async def read_block(c,week):
    i=min((week-1)//8,2);a,b=RANGES[i]
    r=await c.get(f"/plans/v1/plans/{PLAN}/workouts/{a}/{b}")
    n=await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{a}/{b}")
    need(not r.is_error and not n.is_error and isinstance(r.data,list) and isinstance(n.data,list),"BLOCK_READ_FAIL")
    return r.data,digest(n.data),i

def target_from_original(original,spec):
    need(original.get("workoutId")==spec["id"] and original.get("workoutTypeValueId")==1,"WRONG_SWIM_TARGET")
    need(week_of(original)==spec["week"],"WEEK_ID_DRIFT_"+str(spec["id"]))
    q=copy.deepcopy(original)
    q["title"]=spec["title"]
    q["description"]=spec["description"]
    q["distancePlanned"]=float(spec["metres"])
    q["totalTimePlanned"]=spec["minutes"]/60.0
    q["structure"]=structure_for(spec["groups"])
    return q

def final_content_gate(rows,specs):
    by={x["workoutId"]:x for x in rows}
    swims=[x for x in rows if x.get("workoutTypeValueId")==1]
    need(len(swims)==71,"LIVE_SWIM_NOT_71")
    for s in specs:
        w=by[s["id"]]
        need(w.get("title")==s["title"] and w.get("description")==s["description"],"TEXT_DRIFT_"+str(s["id"]))
        need(abs((w.get("distancePlanned") or 0)-s["metres"])<.01,"DISTANCE_DRIFT_"+str(s["id"]))
        need(abs((w.get("totalTimePlanned") or 0)*60-s["minutes"])<.02,"DURATION_DRIFT_"+str(s["id"]))
        st=w.get("structure") or {}
        need(st.get("primaryLengthMetric")=="distance" and st.get("primaryIntensityMetric")=="rpe"
             and len(st.get("structure") or [])>0 and len(st.get("polyline") or [])>0,
             "BUILDER_GATE_"+str(s["id"]))
    # Exact description reuse should not survive the rebuild.
    seen={}
    for w in swims:seen.setdefault(w.get("description") or "",[]).append(w["workoutId"])
    need(max(len(v) for v in seen.values())==1,"EXACT_DESCRIPTION_DUPLICATE_LIVE")
    # Specific continuous markers and distances visible in athlete-facing text.
    whole=[w for w in swims if "4000 m dall'inizio alla fine senza fermarsi" in (w.get("description") or "")]
    need(len(whole)==1 and abs(whole[0].get("distancePlanned")-4000)<.01,"WHOLE_4000_LIVE_GATE")
    return {"swims":71,"unique_descriptions":len(seen),"whole_4000_id":whole[0]["workoutId"]}

async def main():
    specs=build_specs()
    design=design_gate(specs)
    spec_by={x["id"]:x for x in specs}
    target_ids=set(spec_by)
    async with TPClient() as c:
        who=await c._get_user_data()
        need(isinstance(who,dict) and who.get("personId")==OWNER,"WRONG_COACH")
        p=await c.get(f"/plans/v1/plans/{PLAN}")
        h=p.data
        need(not p.is_error and h.get("planId")==PLAN and h.get("planPersonId")==PERSON
             and h.get("isPublic") is False and h.get("workoutCount")==276
             and "CHASING THE SLOT" in (h.get("title") or "") and "BOZZA" in (h.get("title") or ""),
             "PLAN_SCOPE_DRIFT")
        live,live_notes=await read_all(c)
        if BACKUP.exists():
            backup=json.loads(BACKUP.read_text())
            need(backup.get("plan")==PLAN and len(backup.get("original",[]))==249
                 and backup.get("note_hashes")==live_notes,"BACKUP_RECONCILE_REQUIRED")
            original=backup["original"]
        else:
            # First-run source must be exactly 71 swims before we freeze backup.
            need(sum(x.get("workoutTypeValueId")==1 for x in live)==71,"SOURCE_SWIM_COUNT_DRIFT")
            BACKUP.parent.mkdir(parents=True,exist_ok=True)
            BACKUP.write_text(json.dumps({"plan":PLAN,"original":live,"note_hashes":live_notes,
                "target_ids":sorted(target_ids)},ensure_ascii=False,indent=2)+"\n")
            original=live
        orig_by={x["workoutId"]:x for x in original}
        need(target_ids=={x["workoutId"] for x in original if x.get("workoutTypeValueId")==1},
             "TARGET_SET_NOT_ALL_AND_ONLY_SWIM")
        desired={wid:stable(target_from_original(orig_by[wid],spec_by[wid])) for wid in target_ids}
        original_stable={x["workoutId"]:stable(x) for x in original}
        current={x["workoutId"]:stable(x) for x in live}
        # Every live object must be original, except target swims which may already be desired after a partial run.
        for wid,v in current.items():
            if wid in target_ids:
                need(v==original_stable[wid] or v==desired[wid],"LIVE_SWIM_UNKNOWN_DRIFT_"+str(wid))
            else:
                need(v==original_stable[wid],"NON_SWIM_ALREADY_CHANGED_"+str(wid))
        pending=[x for x in specs if current[x["id"]]!=desired[x["id"]]]
        print(json.dumps({"stage":"CHASING_SWIM_REBUILD_PREFLIGHT_PASS","targets":71,"pending":len(pending),
            "design":design,"private":True,"non_swim_protected":178}),flush=True)
        for n,s in enumerate(pending,1):
            wid=s["id"]
            before,bnotes,bi=await read_block(c,s["week"])
            bm={x["workoutId"]:stable(x) for x in before}
            need(bnotes==live_notes[bi] and bm[wid]==current[wid],"PREWRITE_DRIFT_"+str(wid))
            q=target_from_original(orig_by[wid],s)
            res=await c._request("PUT",f"/plans/v1/plans/{PLAN}/workouts/{wid}",json=q,_retry_on_401=False)
            after,anotes,ai=await read_block(c,s["week"])
            am={x["workoutId"]:stable(x) for x in after}
            need(not res.is_error and ai==bi and anotes==live_notes[bi],"WRITE_OR_NOTE_FAIL_"+str(wid))
            need(am[wid]==desired[wid],"POSTWRITE_NOT_VERIFIED_"+str(wid))
            # Everything else in block must equal its expected current state.
            for oid,val in bm.items():
                if oid==wid:continue
                need(am[oid]==val,"UNRELATED_BLOCK_ITEM_CHANGED_"+str(oid))
            current[wid]=desired[wid]
            if n%8==0 or n==len(pending):
                print(json.dumps({"stage":"CHASING_SWIM_REBUILD_PROGRESS","verified":n,"remaining":len(pending)-n,
                    "last_week":s["week"],"last_id":wid}),flush=True)
        final,fn=await read_all(c)
        need(fn==live_notes,"NOTES_CHANGED")
        fm={x["workoutId"]:stable(x) for x in final}
        need(set(fm)==set(original_stable),"WORKOUT_ID_SET_CHANGED")
        need(all(fm[wid]==original_stable[wid] for wid in fm if wid not in target_ids),"NON_SWIM_CHANGED")
        need(all(fm[wid]==desired[wid] for wid in target_ids),"TARGET_NOT_DESIRED")
        liveqa=final_content_gate(final,specs)
        print(json.dumps({"stage":"CHASING_SWIM_REBUILD_PASS","written":len(pending),
            "plan":PLAN,"workouts_total":276,"traditional_workouts":249,
            "swim":liveqa,"design":design,"notes_unchanged":True,"all_workout_ids_preserved":True,
            "bike_run_unchanged":True,"strength_untouched":True,"library_writes":0,
            "athlete_calendar_writes":0,"pdf_writes":0}),flush=True)

if __name__=="__main__":
    try: asyncio.run(main())
    except Exception as e:
        print(json.dumps({"stage":"STOP_CHASING_SWIM_REBUILD","reason":str(e)[:500],
             "verify_provider_before_retry":True}),flush=True)
        raise
