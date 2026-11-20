# IRONMAN — Publisher plan-scoped a manifest unico (v1)

Stato tecnico: **PROVIDER WRITE VERIFIED dal 19 ottobre 2026** per patch in-place alle copie classic Swim/Bike/Run nei Training Plan. Proven Path canonico: `TP-REVIEWED-PATCH-WRITE-028` nel registro Google Drive `00C_IRONMAN_PROVEN_PATHS_REGISTRY`. Il publisher non è legato a un singolo Training Plan: i due job permanenti sono registrati per il coach 2116886 e riutilizzabili; ogni singola pubblicazione richiede un manifest dati aggiornato che identifichi precisamente il piano e i workout target (precondizione di sicurezza, non un nuovo job).

## Obiettivo e perimetro

Un solo motore di pubblicazione di modifiche selettive su **copie classic Swim/Bike/Run già presenti in un Training Plan**. Non sono calendari atleta, non sono nuove istanze, non sono native Strength, non sono note e non sono prodotti marketplace.

Le chiamate a ChatGPT non devono più richiedere ogni volta un nuovo script Python e un nuovo `GUARDED_WRITE` nel registro. Per ogni nuovo lavoro indipendentemente autorizzato si revisiona **soltanto il manifest dei dati**, si fa una commit GitHub e si usa la stessa coppia di job revision-pinned.


## Regola permanente — target esplicito, nessun piano implicito (2026-10-25)

Marker canonico Google Drive: IRONMAN_TARGET_BINDING_HARD_GATE_V1_20261025 (02_DECISION_LOG / 00C Proven Paths / 00 Core).

L'engine e i due job sono UNICI e riutilizzabili per tutti i Training Plan classic. Non creare script/job specifici per ogni piano e non usare il vecchio manifest come indicatore di quale piano stia lavorando il coach. La destinazione deriva dalla richiesta attuale e viene confermata LIVE su TrainingPeaks: coach owner 2116886, plan_id, titolo, visibilità, settimane, conteggi e workout IDs. Un piano non cambia solo perché un file JSON contiene un altro plan_id.

Il formato del manifest resta stabile e unico: i before/after sono dati specifici del lotto e devono necessariamente rappresentare il contenuto da modificare. La loro generazione è automatizzata nell'operazione, non un nuovo motore, e la verifica pre-write deve confrontare l'ID esplicito del target con il manifest e con il provider. Nessun ultimo-file/ultimo-job viene selezionato implicitamente.

PROTEZIONE CODICE nel ramo feat/mcp-test-training-plan-lab: per reviewed_plan_patch_preview/publish con operation=execute il tool tp_ironman_operator richiede target_plan_id esplicito; la pipeline confronta IRONMAN_REQUEST_TARGET_PLAN_ID con manifest.plan_id PRIMA di qualsiasi chiamata provider. Se manca, REQUEST_TARGET_PLAN_ID_REQUIRED; se diverso, STOP_TARGET_MISMATCH. Esempio reale di test negativo: target corrente WINTER FOUNDATION 689369 mentre il vecchio manifest punta a Intermediate 684602 => STOP_TARGET_MISMATCH e zero write. Protezione source-level; NON dichiarare rollout server o provider-live finché test, rilascio e rilettura non sono verificati.

L'ack_scope del job tutela l'autorizzazione, non seleziona il piano. Per pubblicare modifiche serve confermare separatamente l'identità del target e applicare solo il manifest che corrisponde a quella identità. In caso di differenze, interrompere con diagnosi; non toccare piani concorrenti, Library o calendari atleta. Un diniego di sicurezza esplicito sull'operazione specifica non si supera cambiando strumento.

## Elementi stabili

- `scripts/ironman_jobs/reviewed_plan_patch_pipeline.py`: validazione, adapter della API già verificata, backup, controlli e QA.
- `scripts/ironman_jobs/reviewed_plan_patch_preview.py`: analisi read-only, nessun PUT.
- `scripts/ironman_jobs/reviewed_plan_patch_publish.py`: eventuale scrittura solo previo autorizzazione/revisione e scope controllato.
- `data/ironman_reviewed_plan_patch.json`: UNICO file dati da sostituire quando esiste una modifica nuova consentita.
- `reviewed_plan_patch_preview` e `reviewed_plan_patch_publish`: due job permanenti nel registry; non si creano ulteriori job per singoli batch.
- `tests/test_reviewed_plan_patch_pipeline.py`: test completamente offline senza credenziali TP.

Il file dati è inizialmente `configured=false`: **non esiste un batch attivo**, non parte alcuna scrittura involontaria. Il codice non accetta URL generici, comandi, endpoint dall'utente o modifiche al calendario atleta.

## Procedura standard futura

1. Selezionare target, workout IDs e delta concreto con autorizzazione valida; NON ripresentare modifiche già rifiutate dalla piattaforma.
2. Leggere il Training Plan reale e generare il manifest `IRONMAN_PLAN_PATCH_V1` con `plan_id`, titolo esatto, `isPublic` corrente, numero esatto delle istanze, per-workout `before/after`, tipo, data provider e scope univoco.
3. Inserire le finestre del piano in `windows`, il conteggio classic workout e quello delle native Notes; committare solo il manifest (test unitari e review del commit).
4. Eseguire `reviewed_plan_patch_preview` in modalità execute READ_ONLY sul commit pinned: se qualsiasi target differisce dall'originale atteso, ci si ferma senza PUT.
5. Solo dopo approvazione/permesso della classe di operazione: `reviewed_plan_patch_publish` nel perimetro esplicito. Il runner richiede acknowledgement del suo scope e il commit SHA pinned, non accetta una stringa di comandi.
6. Il core scrive backup privati, usa lock, aggiorna solo i campi consentiti, rilegge ogni PUT; in caso di esito ambiguo salva UNCERTAIN e non ripete automaticamente. QA integrale su workout non interessati, note, identità, visibilità e conteggi.
7. Readback provider autonomo finale; registrare il path come PROVEN **solo se** la pubblicazione live ammessa è realmente avvenuta.

## Invarianti e limiti

La durata e la distanza native per Swim e il Builder completo sono prerequisiti; non sostituirli con descrizioni. Il motore usa soltanto campi di patch consentiti dal `plan_patch_batch_core`. Il nome completo `planId` e la visibilità sono precondizioni, non campi da modificare.

Il codice non elimina blocchi o divieti della piattaforma. In particolare, il tentativo precedente di write+restore sul private LAB 684206 ha ricevuto un diniego esplicito: **questo nuovo publisher non va utilizzato come nuovo mezzo per ripetere quell'operazione**. Non si prova a modificare il LAB negato e non si avvia una scrittura di prova su piani commerciali in assenza di uno scope autorizzato. Risolvere eventuali controlli con le procedure ufficiali, non facendo cambiare faccia alla richiesta.

Per una prossima richiesta le operazioni che rimangono ripetibili sono: modificare il JSON, review, CI, preview e (se autorizzato) execute + readback. Il software non va riscritto per ogni piano.
