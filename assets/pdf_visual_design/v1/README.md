# IRONMAN PDF Visual Freeze v1 — schema e componenti

Fonte canonica delle decisioni: **Google Drive / 24_IRONMAN_VISUAL_DESIGN_SYSTEM**. Il codice qui presente è un'implementazione versionata, non un secondo documento metodologico canonico.

## Riferimento approvato

- Guida Atleta Intermediate verificata, Drive `1NW6BIY50CZAgUNwR14lYDIX0sJp06c3r`, SHA-256 `7759224d295123bfdab5203dd82dfc7822228b0a3e60885a6b1003a1b4d7c938`.
- Logo master originale, Drive `1Fl8aJ5zNw8GLTan4oxxMjcv3E6OqELnh`, SHA-256 `ad2710edac3834c467331d2497716c45f8e4cdaf37eaeb658203d531ea9ceea6`. Non ridisegnare né rigenerare il marchio.
- `rpe_scale.svg`: 10 cerchi vettoriali ricostruiti deterministicamente dalle dimensioni e dai colori della pagina 5 APPROVATA. I cerchi 1-4 chiari, 5-7 navy, 8-10 arancio; tutti i numeri al centro. NON usare un nuovo widget CSS improvvisato.
- Simboli `◆ ↳ ◎` canonici. Non convertirli in emoji.
- A4, 18/16/15 mm, palette e gerarchia tipografica descritte nel `contract.json`.

## Tre livelli separati

1. **Blocchi CONGELATI**: marchio, cerchi RPE, simboli e loro presentazione, token e geometrie approvate.
2. **Layout del tipo di PDF**: cover, indici, box, tabelle, grafici, footer. Per l'asset reference è la Guida Intermediate: non inventare un layout differente. Per considerarlo TUTTO congelato mancano sorgente/modello eseguibile e QA visuale completo, non basta questo JSON.
3. **Contenuti e dati sostituibili**: nome piano, descrizioni, test, zone, grafici basati sul calendario reale. Non trasferire protocolli Intermediate al CHASING.

## Gate di QA obbligatorio

Confronto con il PDF master alle medesime dimensioni e risoluzione. Controllare pagina tipo, cover, legenda, RPE, zone, tabella, grafico, footer; controllare eventuali overflow. Versionare qualunque delta approvato; nessuna modifica in silenzio di un blocco congelato. Il QA del componente RPE rileva il vecchio CHASING v1 come FAIL, il corretto v1.1 come PASS.

Questo pacchetto **non** dichiara un confronto pixel-perfect delle 18 pagine; le sorgenti originarie del PDF Intermediate non risultano disponibili. Fino a riproduzione/validazione di tutti i componenti, mantenere lo stato `PARTIAL_IMPLEMENTATION`.
