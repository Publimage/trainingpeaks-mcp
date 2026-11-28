# Strength Builder — stato al 28 novembre 2026

Il codice usa il ramo di integrazione `feat/mcp-test-training-plan-lab`.
La patch per le modifiche parziali va verificata in un calendario TEST con
un allenamento completato associato a un file Garmin e nell'interfaccia web.

## Comandi e percorsi esistenti

| Funzione | Stato rilevato |
| --- | --- |
| Calendario atleta e del coach | `tp_create_strength_workout`, lettura e aggiornamento in-place usano l'API Activity. Il calendario personale va verificato con l'identità atleta self, distinta dall'identità proprietaria del coach. |
| Creazione in Training Plan | Le procedure documentano creazioni native con il calendario tecnico planPersonId. I comandi correnti di scrittura sono circoscritti a piani specifici. |
| Libreria nativa | Il reader Activity e Copy/Move/Delete sono in `organization.py`. Il publisher registrato usa save e copy per manifest approvati. Il reader legacy dei template classici non è prova di una libreria Strength vuota. |
| Piano → atleta | Il ramo `feat/complete-plan-transfer-20261121` contiene un motore con ricevuta e verifica e un'accettazione circolata per Piattaforma TEST 941614. Il codice segue il contratto di una copia integrale del piano. L'esito live va attestato. |
| Altre direzioni | Atleta → atleta/piano/libreria, piano → piano/libreria e libreria → atleta/piano richiedono un percorso unificato con endpoint e readback attestati per la singola seduta. Una copia integrale del piano è un'operazione distinta. |
| Esercizi | `tp_search_exercises` usa una fotografia del catalogo standard. La [UI ufficiale](https://help.trainingpeaks.com/hc/en-us/articles/21397126893581-Using-the-Strength-Workout-Builder) crea esercizi personali con parametri, gruppi muscolari, istruzioni e URL video. Le operazioni via API, l'inventario e la visibilità sui diversi destinatari richiedono verifica. |
| Modifica parziale | `tp_get_strength_workout` espone gli ID di blocco, prescrizione e serie. `tp_update_strength_workout` accetta `prescription_edits` con ID, parametro e valore per modificare in-place più valori esistenti. Supporta anteprima e readback. Stato offline. |

## Verifica e dati

Il preflight in sola lettura del piano 684543 ha restituito
`PROTECTED_RESOURCE`. La lettura indipendente mostra 6 allenamenti e data
iniziale tecnica 2026-10-07, contro i 2 allenamenti e la data 2027-08-02
richiesti dal probe esistente. Prima di una prova di scrittura va convalidato
un target LAB con identità, calendario e finestra aggiornati. La libreria
3890637 è indicata nel registro IRONMAN come libreria di integrazione LAB.

Per le copie, registrare la firma prima della scrittura, rileggere la
destinazione e verificare i campi di prescrizione. Trasferire eventuali
PDF del coach come allegati pianificati e mantenere i file Garmin/FIT, le
misure eseguite e lo storico sul workout originale. Rileggere e verificare
l'originale prima di un eventuale spostamento. Una scrittura con esito incerto
va riconciliata prima del retry. La verifica deve coprire le nove direzioni,
le date relative, il comportamento sui duplicati e l'editor ufficiale.

Williams resta il primo caso applicativo previsto dopo accettazione e
rilascio. Il censimento del 28 novembre nel Workstream State identifica
11 varianti esatte da risolvere via esercizi personali o discovery del
catalogo; si mantengono esercizi, dosi e prescrizioni approvati.
