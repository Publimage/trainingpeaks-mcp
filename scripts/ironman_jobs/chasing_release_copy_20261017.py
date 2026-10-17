"""Remove BOZZA from Chasing title and publish approved HTML while keeping plan private."""
import asyncio, json
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=685173
OLD_TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Italiano | BOZZA"
NEW_TITLE="ALBERTO FAZI ENDURANCE | CHASING THE SLOT | 24 settimane | Advanced | Italiano"
HTML="<div style=\"max-width:900px;margin:auto;font-family:Arial,sans-serif;line-height:1.55;color:#182033;\">\n\n<p style=\"font-size:13px;letter-spacing:1.5px;font-weight:bold;color:#2155d9;margin:0 0 8px;\">ALBERTO FAZI ENDURANCE</p>\n\n<h2 style=\"font-size:30px;line-height:1.15;margin:0 0 14px;\">CHASING THE SLOT — 24 settimane | Advanced</h2>\n\n<p style=\"font-size:18px;color:#4b5563;margin:0 0 24px;\">Programma per triatleti full distance esperti che vogliono preparare una gara-obiettivo con un’impostazione più prestativa, maggiore specificità e una gestione precisa del carico nelle 24 settimane.</p>\n\n<div style=\"margin:24px 0;padding:19px;border-left:4px solid #2155d9;background:#f6f8fc;\">\n<strong style=\"font-size:19px;\">PREREQUISITI</strong><br><br>\nEsperienza sulla lunga distanza, continuità di allenamento già consolidata e buona tolleranza al volume. In bici il misuratore di potenza e un FTP attendibile sono fortemente raccomandati, perché una parte importante della prescrizione viene eseguita tramite Builder in %FTP.\n</div>\n\n<div style=\"margin:24px 0;padding:19px;background:#f6f8fc;border-radius:8px;\">\n<strong style=\"font-size:19px;\">3 GUIDE INCLUSE</strong><br><br>\n<strong>Guida Atleta</strong> — come leggere ed eseguire il programma.<br><br>\n<strong>Guida Settimana per Settimana</strong> — logica, progressione e obiettivi dei blocchi.<br><br>\n<strong>Fueling & Nutrizione</strong> — indicazioni pratiche per costruire, testare e consolidare la strategia alimentare e di idratazione.\n</div>\n\n<h2 style=\"font-size:25px;margin:32px 0 16px;\">Che cosa cambia rispetto a un piano Intermediate</h2>\n\n<p>\n<strong>Maggiore volume complessivo</strong> — con due settimane di picco fino a circa 20 ore reali.<br><br>\n<strong>Weekend più specifici</strong> — con maggiore densità di lavoro, brick e sedute lunghe sotto fatica controllata.<br><br>\n<strong>Bici power-first</strong> — i segmenti strutturati utilizzano riferimenti in %FTP, con RPE mantenuto nel testo come controllo secondario.<br><br>\n<strong>Corsa strutturata</strong> — riferimenti in percentuale del Run Threshold Pace quando il dato è valido, con RPE complementare.<br><br>\n<strong>Durability e race execution</strong> — capacità di mantenere ritmo, tecnica, posizione aero e alimentazione quando aumenta la durata.<br><br>\n<strong>Fueling e gestione gara</strong> — integrati nelle sedute chiave e non rimandati alle ultime settimane.\n</p>\n\n<h2 style=\"font-size:25px;margin:32px 0 14px;\">24 settimane costruite per una gara-obiettivo</h2>\n\n<p>Il programma alterna sviluppo, recupero e blocchi specifici fino alla fase finale. Il lavoro non consiste semplicemente nell’aumentare le ore: volume, intensità, recupero, posizione, brick, ritmo gara e strategia nutrizionale vengono organizzati come parti dello stesso processo.</p>\n\n<div style=\"margin:24px 0;padding:18px;background:#111827;color:white;border-radius:8px;\">\n<strong>PIÙ VOLUME RICHIEDE PIÙ CONTROLLO.</strong><br><br>\nIl piano è pensato per un atleta che possiede già la base necessaria per assorbire carichi elevati e che sa monitorare con attenzione recupero, risposta allo sforzo e qualità dell’esecuzione.\n</div>\n\n<h2 style=\"font-size:25px;margin:32px 0 14px;\">Obiettivo prestativo, senza promesse sul risultato</h2>\n\n<p>CHASING THE SLOT è costruito per preparare in modo completo un atleta già competitivo alla propria gara-obiettivo. Non può garantire una qualificazione: il risultato dipende anche dal livello individuale, dalla categoria, dalla gara scelta, dalle condizioni e dalla concorrenza presente quel giorno.</p>\n\n<div style=\"margin:30px 0 0;padding:22px;background:#f6f8fc;border-radius:8px;\">\n<strong style=\"font-size:20px;\">Prima di iniziare</strong><br><br>\nQuesto non è un piano per costruire da zero la base necessaria alla lunga distanza. Se devi ancora consolidare continuità, volume e gestione delle tre discipline, il livello Intermediate è il passaggio più adatto prima di affrontare CHASING THE SLOT.\n</div>\n\n</div>"
EXPECTED_WORKOUTS=276
EXPECTED_WEEKS=24
class Stop(Exception): pass
def must(v,msg):
    if not v: raise Stop(msg)
async def go():
    async with TPClient() as c:
        me=await c._get_user_data()
        must(isinstance(me,dict) and me.get("personId")==OWNER,"WRONG_OWNER")
        r=await c.get(f"/plans/v1/plans/{PLAN}")
        must(not r.is_error and isinstance(r.data,dict),"PLAN_READ_FAIL")
        p=r.data
        must((p.get("planId"),p.get("weekCount"),p.get("workoutCount"))==(PLAN,EXPECTED_WEEKS,EXPECTED_WORKOUTS),"PLAN_SCOPE_MISMATCH")
        must(p.get("title") in (OLD_TITLE,NEW_TITLE),"TITLE_DRIFT")
        must(p.get("isPublic") is False and p.get("price") in (None,0),"PLAN_VISIBILITY_DRIFT")
        plans=await c.get("/plans/v1/plans")
        must(not plans.is_error and isinstance(plans.data,list),"PLAN_LIST_FAIL")
        must(not any(x.get("planId")!=PLAN and (x.get("title") or "").casefold()==NEW_TITLE.casefold() for x in plans.data),"TITLE_COLLISION")
        for k in ("author","planEmail","planLanguage"):
            must(p.get(k) not in (None,""),"PLAN_METADATA_MISSING:"+k)
        baseline={k:v for k,v in p.items() if k not in ("title","description")}
        if p.get("title")==NEW_TITLE and p.get("description")==HTML:
            print("CHASING_RELEASE_COPY_ALREADY_PRESENT_VERIFIED")
            return 0
        put=await c._request("PUT",f"/plans/v1/plans/{PLAN}",
            json={"planId":PLAN,"title":NEW_TITLE,"description":HTML,
                  "author":p["author"],"planEmail":p["planEmail"],"planLanguage":p["planLanguage"]},
            _retry_on_401=False)
        if put.is_error:
            print("STOP_WRITE_RESULT_UNCLEAR",put.error_code,str(put.message)[:120],flush=True)
            return 2
        r2=await c.get(f"/plans/v1/plans/{PLAN}")
        must(not r2.is_error and isinstance(r2.data,dict),"PLAN_READBACK_FAIL")
        p2=r2.data
        must(p2.get("title")==NEW_TITLE,"TITLE_READBACK_FAILED")
        must(p2.get("description")==HTML,"DESCRIPTION_READBACK_FAILED")
        changed={k for k in set(baseline)|set(p2) if k not in ("title","description") and baseline.get(k)!=p2.get(k)}
        must(all(("modif" in k.lower() or "updat" in k.lower()) for k in changed),"UNEXPECTED_DRIFT:"+",".join(sorted(changed)))
        must(p2.get("isPublic") is False and p2.get("price") in (None,0),"VISIBILITY_CHANGED")
        print("CHASING_RELEASE_COPY_VERIFIED")
        print(json.dumps({"plan_id":PLAN,"title":NEW_TITLE,"html_chars":len(HTML),"workouts":p2.get("workoutCount"),"weeks":p2.get("weekCount"),"is_public":p2.get("isPublic")},ensure_ascii=False))
        return 0
if __name__=="__main__":
    try: raise SystemExit(asyncio.run(go()))
    except Stop as e:
        print("STOP_REVIEW",str(e),flush=True); raise SystemExit(2)
