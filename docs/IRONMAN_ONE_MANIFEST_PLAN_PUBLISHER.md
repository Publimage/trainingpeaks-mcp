# IRONMAN — Publisher plan-scoped a manifest unico (v1)

Stato tecnico: **implementato in ramo review; CI da completare, scrittura live NON verificata**.

## Obiettivo e perimetro

Un solo motore di pubblicazione di modifiche selettive su **copie classic Swim/Bike/Run già presenti in un Training Plan**. Non sono calendari atleta, non sono nuove istanze, non sono native Strength, non sono note e non sono prodotti marketplace.

Le chiamate a ChatGPT non devono più richiedere ogni volta un nuovo script Python e un nuovo `GUARDED_WRITE` nel registro. Per ogni nuovo lavoro indipendentemente autorizzato si revisiona **soltanto il manifest dei dati**, si fa una commit GitHub e si usa la stessa coppia di job revision-pinned.

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
