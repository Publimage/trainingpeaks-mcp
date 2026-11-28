# Training Plan editor — contratto operativo v1 (16 ottobre 2026)

**Stato: PROPOSTA TECNICA / NON DEPLOYATO.** Nessun workout è stato modificato da questo documento.

## Problema e obiettivo
Ridurre il lavoro ripetitivo dentro la chat. ChatGPT e il coach stabiliscono cambiamenti e vincoli fisiologici; un unico esecutore esterno prepara un diff su dati reali, convalida Builder e consistenza delle ore, modifica in-place solo le copie autorizzate nei Training Plan privati, conserva backup/evidenze e restituisce un rapporto sintetico. Non sviluppare altra infrastruttura: riusare il server TrainingPeaks, `tp_ironman_operator`, il trusted job registry revision-pinned e, quando pronto, Prefect per gestione del ciclo di vita.

## Primo caso reale
- Fonte canonica: Google Drive `15_FIRST_IRONMAN_24W_PRODUCT_SPEC`, sezione `MATRICE RIVISTA 2026-10-16`.
- Manifest: `data/ironman_manifests/beginner_run_bike_balance_20261016.json` — sette coppie / 14 workout ID del solo plan privato **679801**, W13/14/15/17/18/19/21.
- Invariante: RUN -105', BI +105', delta settimanale e totale **zero**; W19 RUN 140' -> 120', BI 70' -> 90'. Nuoto, forza, note, brick e workout non selezionati immutati.
- Durate/step sono candidate approvate come direzione dal coach ma ancora soggette alla verifica delle strutture native e del carico; il manifesto NON autorizza di per sé una scrittura.

## Implementazione minima accettabile
1. **Preview server READ_ONLY**: leggere piano/provider owner/private status, singoli workout nativi completi, tutti i workout e le note delle sette settimane, identificazione per Wnn+D1..7+UID. Conservare snapshot e hash originali; usare fonti Drive vigenti e bloccare conflitti o assenza di fonti.
2. **Patch selettiva**: editare SOLO il fondo facile prescritto e approvato dei RUN e aggiungere SOLTANTO endurance bike sotto LT1. Preservare blocchi intensi (%FTP/%RunThreshold), ripetizioni, recovery, contenuto non interessato, ID, titoli conformi, descrizione, targets, polilinea nativa. Rifiutare silenziose incoerenze tra top-level planned duration e somma dei Builder. Non fare POST+DELETE, non usare l'API di calendario atleta, non modificare Library.
3. **Fail-closed e prova**: owner 2116886, piano 679801 privato, manifest e codice pin di revisione, allowlist degli ID, controllo fingerprint prima di ogni PUT, backup privato durevole, golden-first su piano sacrificabile e poi una sola coppia, GET dopo ogni PUT, confronto esatto invarianti e note, report e ripartenza idempotente senza duplicazioni.
4. **Piano QA**: test su Builder semplici, ripetuti, mancanti e inconsistenza testo/durata; difformità di owner, piano pubblico, differenza di settimana, duplicato, mismatch soglia/target, timeout dopo scrittura, ripartenza da backup e difformità contemporanea. Nessun rilascio pubblico fino al publishing gate completo.
5. **Prestazioni**: conservare i dettagli nel ledger/server e restituire a ChatGPT solo manifest ID, delta, PASS/FAIL, incongruenze e riferimenti. Confrontare in modo misurabile numero di chiamate, latenza, input/output del modello e qualità contro il precedente lavoro in chat.

## Stato e blocco concreto
- Manifest JSON GitHub **INSERITO E VERIFICATO** (commit `3f041c396b55ee5940566471fd53c60cdfed76b2`).
- Codice dell'editor **NON CREATO**, nessun job aggiunto al registry, nessun test server/TrainingPeaks eseguito.
- La creazione del modulo Python condiviso tramite connettore GitHub è stata **esplicitamente bloccata da un controllo di sicurezza OpenAI**. Non tentare vie alternative per eludere il diniego.
- Le GitHub Issues nel repository sono disabilitate (API HTTP 410).
- Nessuna spesa o nuovo server autorizzato da questa specifica.

Questo documento è un contratto tecnico e un punto di ripresa, **non la prova di uno strumento funzionante**.
