"""Publish the approved HTML summary to private Intermediate plan 684602 only."""
import asyncio, json
from tp_mcp.client import TPClient
OWNER=2116886
PLAN=684602
TITLE="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"
HTML="<div style=\"max-width:900px;margin:auto;font-family:Arial,sans-serif;line-height:1.55;color:#182033;\">\n\n<p style=\"font-size:13px;letter-spacing:1.5px;font-weight:bold;color:#2155d9;margin:0 0 8px;\">ALBERTO FAZI ENDURANCE</p>\n\n<h2 style=\"font-size:30px;line-height:1.15;margin:0 0 14px;\">IRONMAN 24 settimane — Intermediate</h2>\n\n<p style=\"font-size:18px;color:#4b5563;margin:0 0 24px;\">Programma per triatleti che hanno già costruito una base di allenamento e vogliono preparare un full distance con una progressione più completa di volume, specificità e riferimenti di intensità.</p>\n\n<div style=\"margin:24px 0;padding:19px;border-left:4px solid #2155d9;background:#f6f8fc;\">\n<strong style=\"font-size:19px;\">A CHI È RIVOLTO</strong><br><br>\nAtleti con esperienza nel triathlon, continuità di allenamento già consolidata e capacità di gestire una preparazione strutturata su nuoto, bici, corsa e forza. Non è un programma di ingresso alla distanza: parte da una base già presente e la sviluppa nelle 24 settimane.\n</div>\n\n<div style=\"margin:24px 0;padding:19px;background:#f6f8fc;border-radius:8px;\">\n<strong style=\"font-size:19px;\">3 GUIDE INCLUSE</strong><br><br>\n<strong>Guida Atleta</strong> — come leggere ed eseguire il programma.<br><br>\n<strong>Guida Settimana per Settimana</strong> — logica e obiettivi dei blocchi di lavoro.<br><br>\n<strong>Fueling & Nutrizione</strong> — indicazioni pratiche per costruire e provare in allenamento la strategia alimentare e di idratazione.\n</div>\n\n<h2 style=\"font-size:25px;margin:32px 0 16px;\">Struttura del programma</h2>\n\n<p>\n<strong>Workout strutturati</strong> — nuoto, bici e corsa con indicazioni progressive e riferimenti di intensità.<br><br>\n<strong>Forza integrata</strong> — inserita nella periodizzazione e non aggiunta come blocco separato.<br><br>\n<strong>Test e calibrazione</strong> — per aggiornare i riferimenti individuali durante il percorso.<br><br>\n<strong>Doppia lettura dello sforzo</strong> — RPE sempre utilizzabile, con potenza, passo o frequenza cardiaca quando disponibili e appropriati.<br><br>\n<strong>Brick, posizione aero e ritmo gara</strong> — introdotti e sviluppati in modo progressivo.<br><br>\n<strong>Fueling</strong> — allenato insieme alla durata e alla specificità delle sedute chiave.\n</p>\n\n<h2 style=\"font-size:25px;margin:32px 0 14px;\">24 settimane di progressione</h2>\n\n<p>Il carico cresce attraverso blocchi di sviluppo e settimane di recupero, con un aumento graduale della durata delle sedute chiave e della specificità del lavoro. L'obiettivo è arrivare alla race week avendo già provato in allenamento ritmo, posizione, brick, gestione dello sforzo e strategia di alimentazione.</p>\n\n<div style=\"margin:24px 0;padding:18px;background:#111827;color:white;border-radius:8px;\">\n<strong>IL VOLUME È SOLO UNA PARTE DELLA PREPARAZIONE.</strong><br><br>\nLa progressione viene costruita insieme a qualità, recupero, durata, tecnica e capacità di mantenere il lavoro previsto quando aumenta la fatica.\n</div>\n\n<h2 style=\"font-size:25px;margin:32px 0 14px;\">Non serve obbligatoriamente un misuratore di potenza</h2>\n\n<p>Il piano può essere eseguito anche utilizzando percezione dello sforzo e gli altri riferimenti individuali disponibili. Quando l'atleta dispone di dati affidabili, i workout strutturati possono utilizzare anche potenza, passo o frequenza cardiaca per rendere l'esecuzione più precisa.</p>\n\n<div style=\"margin:30px 0 0;padding:22px;background:#f6f8fc;border-radius:8px;\">\n<strong style=\"font-size:20px;\">Prima di iniziare</strong><br><br>\nQuesto programma è indicato per chi arriva alle 24 settimane con una base già costruita e una routine regolare nelle tre discipline. Se stai iniziando ora il percorso verso il tuo primo full distance, il piano Beginner è il punto di ingresso più adatto.\n</div>\n\n</div>"
EXPECTED_WORKOUTS=259
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
        must((p.get("planId"),p.get("title"),p.get("weekCount"),p.get("workoutCount"))==(PLAN,TITLE,EXPECTED_WEEKS,EXPECTED_WORKOUTS),"PLAN_SCOPE_MISMATCH")
        must(p.get("isPublic") is False and p.get("price") in (None,0),"PLAN_VISIBILITY_DRIFT")
        for k in ("author","planEmail","planLanguage"):
            must(p.get(k) not in (None,""),"PLAN_METADATA_MISSING:"+k)
        before={k:v for k,v in p.items() if k!="description"}
        if p.get("description")==HTML:
            print("INTERMEDIATE_HTML_ALREADY_PRESENT_VERIFIED")
            return 0
        put=await c._request("PUT",f"/plans/v1/plans/{PLAN}",
            json={"planId":PLAN,"title":TITLE,"description":HTML,
                  "author":p["author"],"planEmail":p["planEmail"],"planLanguage":p["planLanguage"]},
            _retry_on_401=False)
        if put.is_error:
            print("STOP_WRITE_RESULT_UNCLEAR",put.error_code,str(put.message)[:120],flush=True)
            return 2
        r2=await c.get(f"/plans/v1/plans/{PLAN}")
        must(not r2.is_error and isinstance(r2.data,dict),"PLAN_READBACK_FAIL")
        p2=r2.data
        must(p2.get("description")==HTML,"DESCRIPTION_READBACK_FAILED")
        changed={k for k in set(before)|set(p2) if k!="description" and before.get(k)!=p2.get(k)}
        must(all(("modif" in k.lower() or "updat" in k.lower()) for k in changed),"UNEXPECTED_DRIFT:"+",".join(sorted(changed)))
        must(p2.get("isPublic") is False and p2.get("price") in (None,0),"VISIBILITY_CHANGED")
        print("INTERMEDIATE_HTML_VERIFIED")
        print(json.dumps({"plan_id":PLAN,"title":TITLE,"html_chars":len(HTML),"workouts":p2.get("workoutCount"),"weeks":p2.get("weekCount"),"is_public":p2.get("isPublic")},ensure_ascii=False))
        return 0
if __name__=="__main__":
    try: raise SystemExit(asyncio.run(go()))
    except Stop as e:
        print("STOP_REVIEW",str(e),flush=True); raise SystemExit(2)
