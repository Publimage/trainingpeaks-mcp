# IRONMAN — Classificazione corretta dello stato read-only del publisher

Problema concreto osservato il 18/10/2026: in un'altra chat IRONMAN un tentativo di eseguire la verifica tramite `tp_ironman_operator(operation="execute", job="reviewed_plan_patch_preview")` e' stato negato dal livello di sicurezza ChatGPT, prima di qualsiasi scrittura TrainingPeaks. Lo stesso controllo era riuscito in un'altra sessione. Non significa che TrainingPeaks abbia negato la lettura o che il publisher abbia provato a scrivere.

## Causa strutturale verificata nel codice

Il tool `tp_ironman_operator` e' correttamente classificato in MCP con `readOnlyHint=false` e `idempotentHint=false`. Il motivo: `execute` effettua checkout del repository, esegue script su cloud e puo' avviare job GUARDED_WRITE. Anche il suo parametro `preview` effettua verifica revisioni e puo' interagire con git. Non e' onesto rinominare o riclassificare il tool misto come read-only.

La connessione "TrainingPeaks MCP" risulta con permesso ChatGPT `Use my default`, default `Allow low-risk actions`. Questo **puo' contribuire** alla valutazione dell'operatore misto come rischioso; non e' una prova della decisione interna del filtro.

## Soluzione di separazione corretta

Aggiunto tool nativo MCP `tp_get_ironman_publisher_status` (READ ONLY effettivo):
- Autentica il coach 2116886 con GET, mai cambia target atleta.
- Legge soltanto i file locali del manifest e del registry nel runtime, senza checkout/fetch GitHub, senza subprocess, senza PUT/POST o mutazioni filesystem.
- Espone in modo esplicito `manifest_configured`, presenza dei due job e `live_writer_verified=false`, per impedire l'equivoco "preview pass = publisher LIVE".
- Nella descrizione del tool e nell'annotazione MCP usa `readOnlyHint=true`. Il vecchio `tp_ironman_operator` resta correttamente non-read-only, protetto come prima.

La nuova operazione e' **diversa** dall'esecuzione del precedente job: ispeziona solo lo stato del manifest, non esegue la richiesta esplicitamente negata. Non tentare di riprodurre l'azione negata usando questo tool o altri endpoint, ne' mutare i permessi automaticamente. Per completare un write reale resta necessario scope autorizzato e verifica del provider.

## Stato del rollout

Il codice e i test su GitHub non significano che il tool sia gia esposto nel catalogo della chat. Sono necessari integrazione/deploy ufficiali del server MCP e refresh del catalogo nel client. Il nome comparira' come tool solo dopo quel passaggio. Non dichiarare DONE se e' soltanto merged.

I casi di rifiuto pre-dispatch restano possibili. Per le sole letture TrainingPeaks continuare a preferire i tool gia esistenti `tp_get_training_plan_workouts` e `tp_get_training_plan`; per controllo stato nuovo basta status tool dopo deploy. Per scritture non ricorrere a un altro mezzo per eludere un diniego.
