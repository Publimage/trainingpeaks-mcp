"""Write approved 70.3 Beginner product description in private plan ONLY.

Based on the previously verified Intermediate/Chasing HTML-only plan PUT
route. Preserve all other plan metadata, notes, PDFs, and 133 workouts.
Run only through the revision-pinned reviewed IRONMAN operator.
"""
from __future__ import annotations
import asyncio
import json
import hashlib
from tp_mcp.client import TPClient

OWNER = 2116886
PLAN = 686994
TITLE = "ALBERTO FAZI ENDURANCE | 70.3 | 16 settimane | Beginner | Italiano"
HTML = '''<div style="max-width:900px;margin:auto;font-family:Arial,sans-serif;line-height:1.55;color:#182033;">

<p style="font-size:13px;letter-spacing:1.5px;font-weight:bold;color:#2155d9;margin:0 0 8px;">ALBERTO FAZI ENDURANCE</p>

<h2 style="font-size:30px;line-height:1.15;margin:0 0 14px;">70.3 &mdash; 16 settimane | Beginner</h2>

<p style="font-size:18px;color:#4b5563;margin:0 0 24px;">Un programma di preparazione per triatleti amatori che praticano gi&agrave; nuoto, ciclismo e corsa e vogliono affrontare il primo 70.3. Sedici settimane di lavoro progressivo per sviluppare resistenza, continuit&agrave; e capacit&agrave; di gestire le tre frazioni senza arrivare alla corsa con le energie esaurite.</p>

<div style="margin:24px 0;padding:19px;border-left:4px solid #2155d9;background:#f6f8fc;">
<strong style="font-size:19px;">A CHI &Egrave; RIVOLTO</strong><br><br>
A chi ha gi&agrave; una pratica regolare delle tre discipline e vuole organizzare la preparazione al primo mezzo Ironman con un calendario strutturato, compatibile con gli impegni della vita quotidiana. Non &egrave; un programma per iniziare a nuotare, pedalare o correre da zero: &egrave; necessaria una base di allenamento e la capacit&agrave; di praticare il nuoto in sicurezza.
</div>

<div style="margin:24px 0;padding:19px;background:#f6f8fc;border-radius:8px;">
<strong style="font-size:19px;">2 GUIDE PDF INCLUSE</strong><br><br>
<strong>Guida Atleta 70.3 Beginner</strong> &mdash; come utilizzare TrainingPeaks, leggere i workout strutturati, interpretare RPE e riferimenti individuali, gestire recupero e sedute saltate.<br><br>
<strong>Scheda pratica Gara e Alimentazione</strong> &mdash; indicazioni per provare alimentazione e idratazione negli allenamenti, organizzare le transizioni e compilare una checklist personale prima della gara.<br><br>
Nel calendario sono presenti anche <strong>16 note educative settimanali</strong>: spiegano il lavoro della settimana, le priorit&agrave; e ci&ograve; che &egrave; utile osservare durante gli allenamenti.
</div>

<h2 style="font-size:25px;margin:32px 0 16px;">Struttura del programma</h2>

<p>
<strong>133 allenamenti programmati</strong> &mdash; nuoto, bici, corsa e 15 sedute di forza con struttura nativa TrainingPeaks.<br><br>
<strong>Nuoto</strong> &mdash; tecnica, efficienza e progressione della continuit&agrave; verso i 1.900 metri, con attenzione alla sicurezza in acque libere.<br><br>
<strong>Bici</strong> &mdash; resistenza aerobica, regolarit&agrave;, controllo dello sforzo, posizione sostenibile e alimentazione durante i lunghi.<br><br>
<strong>Corsa</strong> &mdash; sviluppo graduale della tolleranza al carico e del ritmo sostenibile, anche dopo la frazione ciclistica.<br><br>
<strong>Forza integrata</strong> &mdash; sedute distribuite nella programmazione, con esercizi, serie e recuperi indicati.<br><br>
<strong>Brick e prove pratiche</strong> &mdash; transizioni bici-corsa e occasioni per verificare materiali, ritmo e fueling senza trasformare ogni lungo in una simulazione di gara.
</p>

<h2 style="font-size:25px;margin:32px 0 14px;">16 settimane di progressione</h2>

<p>Le prime settimane consolidano routine, tecnica e fondo aerobico. Seguono uno sviluppo controllato dei lunghi, settimane di assorbimento e un lavoro sempre pi&ugrave; specifico sulla gestione della bici e sulla corsa successiva. Le settimane 13 e 14 comprendono prove pratiche parziali di gara; le ultime due riducono il carico e preparano l'arrivo alla competizione.</p>

<p>Il luned&igrave; &egrave; normalmente libero. Il lungo di corsa &egrave; previsto al sabato, quello in bici alla domenica; i brick sono inseriti soltanto nelle settimane in cui hanno una funzione precisa. La gara della sedicesima settimana &egrave; distinta dalle ore di allenamento di attivazione.</p>

<div style="margin:24px 0;padding:18px;background:#111827;color:white;border-radius:8px;">
<strong>Allenarsi al ritmo previsto conta pi&ugrave; che aggiungere minuti.</strong><br><br>
Il programma alterna lavoro e recupero per permettere di progredire senza cercare di recuperare tutte le sedute perse o trasformare gli allenamenti facili in prove di prestazione.
</div>

<h2 style="font-size:25px;margin:32px 0 14px;">Puoi seguirlo anche senza misuratore di potenza</h2>

<p>La percezione dello sforzo (RPE) &egrave; un riferimento centrale del livello Beginner. Potenza, frequenza cardiaca e passo possono aiutare a controllare l'esecuzione quando sono disponibili e affidabili, ma il piano non richiede di possedere un misuratore di potenza. Le indicazioni dei singoli workout spiegano come eseguire la seduta e quali segnali osservare.</p>

<h2 style="font-size:25px;margin:32px 0 14px;">Preparare anche l'alimentazione e la gestione della gara</h2>

<p>Nei lunghi e nelle sedute pertinenti impari a provare prodotti, quantit&agrave; e frequenza di assunzione compatibili con la tua tolleranza. Il materiale incluso aiuta a registrare le prove e a preparare una strategia realistica per nuoto, bici, corsa e transizioni, senza imporre un unico protocollo alimentare a tutti gli atleti.</p>

<div style="margin:30px 0 0;padding:22px;background:#f6f8fc;border-radius:8px;">
<strong style="font-size:20px;">Prima di iniziare</strong><br><br>
Questo &egrave; un Training Plan <em>self-guided</em> di 16 settimane. Prima di applicarlo, verifica di avere una base recente e sufficiente nelle tre discipline e di poter sostenere la progressione prevista. Leggi la nota <strong>README FIRST | INIZIA DA QUI</strong> e i due PDF allegati nella prima settimana. Il programma non comprende coaching individuale o modifiche continuative da parte dell'autore.
</div>

</div>
'''
NOTE = 2672039
ATTACHMENTS = {
    "70_3_Beginner_16W_Guida_Atleta_DEFINITIVA.pdf": (97606, 383566),
    "70_3_Beginner_16W_Scheda_Gara_e_Alimentazione_v0_1.pdf": (97607, 322297),
}
NOTE_START = "2027-01-04"
NOTE_END = "2027-04-29"

class SafeStop(Exception):
    pass

def must(test: bool, code: str) -> None:
    if not test:
        raise SafeStop(code)

async def run() -> int:
    async with TPClient() as c:
        me = await c._get_user_data()
        must(isinstance(me, dict) and me.get("personId") == OWNER, "OWNER_MISMATCH")
        owned = await c.get("/plans/v1/plans")
        must(not owned.is_error and isinstance(owned.data, list), "COACH_PLANS_UNAVAILABLE")
        must(any(p.get("planId") == PLAN for p in owned.data), "PLAN_NOT_COACH_OWNED")

        async def detail():
            d = await c.get(f"/plans/v1/plans/{PLAN}")
            must(not d.is_error and isinstance(d.data, dict), "PLAN_READ_FAILED")
            return d.data

        async def notes():
            n = await c.get(f"/plans/v1/plans/{PLAN}/calendarNote/{NOTE_START}/{NOTE_END}")
            must(not n.is_error and isinstance(n.data, list), "NOTES_READ_FAILED")
            return n.data

        p = await detail()
        must(p.get("planId") == PLAN and p.get("title") == TITLE
             and p.get("weekCount") == 16 and p.get("workoutCount") == 133,
             "TARGET_PLAN_MISMATCH")
        must(p.get("isPublic") is False and p.get("price") in (None,0),
             "NOT_PRIVATE_UNPRICED")
        must(p.get("description") in (None, "", HTML), "DESCRIPTION_CONFLICT")
        for k in ("author", "planEmail", "planLanguage"):
            must(p.get(k) not in (None, ""), "REQUIRED_PLAN_METADATA_MISSING_"+k)

        prior_notes = await notes()
        must(len(prior_notes) == 17
             and len({n.get("id") for n in prior_notes}) == 17,
             "NOTES_INVENTORY_MISMATCH")
        target = next((n for n in prior_notes if n.get("id") == NOTE), None)
        must(target is not None and target.get("title") == "README FIRST | INIZIA DA QUI",
             "README_NOT_FOUND")
        attached = target.get("attachments") or []
        must(len(attached) == 2
             and all(len([a for a in attached
                          if a.get("fileName") == filename
                          and a.get("id") == identifier
                          and a.get("contentLength") == size]) == 1
                     for filename, (identifier, size) in ATTACHMENTS.items()),
             "README_PDF_INVENTORY_MISMATCH")
        if p.get("description") == HTML:
            print("70_3_DESCRIPTION_ALREADY_PRESENT_VERIFIED",flush=True)
            return 0
        baseline = {k:v for k,v in p.items() if k != "description"}
        put = await c._request(
            "PUT", f"/plans/v1/plans/{PLAN}",
            json={"planId": PLAN, "title": TITLE, "description": HTML,
                  "author": p["author"], "planEmail": p["planEmail"],
                  "planLanguage": p["planLanguage"]},
            _retry_on_401=False,
        )
        # A provider write may commit despite a rejected/ambiguous response.
        # Always reconcile by GET; never retry blindly.
        p2 = await detail()
        if p2.get("description") != HTML:
            print("STOP_WRITE_NOT_VERIFIED",
                  json.dumps({"provider_error":str(getattr(put,"error_code",None)),
                              "description_is_original":p2.get("description")==p.get("description")}),
                  flush=True)
            return 2
        changed = {k for k in set(baseline)|set(p2)
                   if k != "description" and baseline.get(k) != p2.get(k)}
        must(all(("modif" in k.lower() or "updat" in k.lower()) for k in changed),
             "OTHER_PLAN_METADATA_CHANGED:"+",".join(sorted(changed)))
        must(p2.get("isPublic") is False and p2.get("price") in (None,0)
             and p2.get("workoutCount") == 133 and p2.get("weekCount") == 16
             and p2.get("title") == TITLE,
             "PLAN_SCOPE_DRIFT")
        after_notes = await notes()
        must(json.dumps(after_notes, sort_keys=True, ensure_ascii=False)
             == json.dumps(prior_notes, sort_keys=True, ensure_ascii=False),
             "NOTES_PDFS_CHANGED")
        print("70_3_BEGINNER_MARKETPLACE_HTML_VERIFIED",
              json.dumps({"plan_id":PLAN,"description_chars":len(HTML),
                          "sha256":hashlib.sha256(HTML.encode("utf-8")).hexdigest(),
                          "notes":17,"pdfs":2,"workouts":133,"weeks":16,
                          "public":False,"price":p2.get("price")},
                         ensure_ascii=False), flush=True)
        return 0

if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run()))
    except SafeStop as exc:
        print("STOP_REVIEW", str(exc), flush=True)
        raise SystemExit(2)
