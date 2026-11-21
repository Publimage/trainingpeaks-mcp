# IRONMAN XLSX fast patch v1 — reviewed and tested offline

**Technical entrypoint (not the methodological source of truth).** The canonical IRONMAN source remains the live Google Drive KB: `00_IRONMAN_CORE_INDEX` → `10_CHAT_ARCHITECTURE_AND_ROLLOVER` (CASE ROUTER) → relevant Product Card/State → `00C_IRONMAN_PROVEN_PATHS_REGISTRY`. Do not read whole documents when the task requires only an applicable passage. The source XLSX must be resolved from the current Library file/version, never guessed from a prior chat.

**Scope:** low-risk, localized changes to *existing text cells* of a workbook. It can patch multiple representations in a single transaction when the manifest explicitly lists every expected cell. It discovers text within a relative training week, computes an exact pre/post diff, refuses stale files/unknown preimages, preserves untouched XLSX parts, cached formulas, charts and styles, and verifies the output independently. It makes **zero** TrainingPeaks, GitHub, athlete calendar or Google Drive writes. Do not run on commercial provider files.

**Not supported yet:** automatic discovery of all semantic mirrors solely from a workout description; numeric volume/time changes, Builder prescription changes, formula/chart recalculation, rich-text cell runs, published provider writes. These are fail-closed and must be reviewed as block/structural changes. A matched text edit is not authorization of a new workout prescription.

## Practical procedure from a *new chat*

1. Search live Drive CORE, MASTER, DECISION, OPEN, `10` and `00C` **by title**, but open only the matching original passages. Read the CHASING Product Card and latest checkpoint (or target product's own Card/State). Search the Library for the currently valid XLSX and obtain its exact `file_id`, version and SHA256. The user should not need to upload the same file again when Library access works.
2. Retrieve `scripts/ironman_jobs/ironman_xlsx_patch.py` from this GitHub repo's tested branch (or its reviewed merged ref). Use Python with `openpyxl`. `inspect` to identify week, row, day, workout ID where present and mirrored cells; prepare exact manifest against SHA256. Manifest **must** contain each changed cell's full current `before` and full desired `after` strings; no uncontrolled replace-all.
3. `preview` decides the A/B/C risk route based on scope, numeric dose/volume and semantic stimulus changes. A_LOCAL can be applied to **a separate copy**. B_BLOCK_REVIEW_STOP / C_STRUCTURAL_STOP requires more context and a different reviewed workflow; do not retry with an invented approval flag.
4. `apply` runs an atomic copy-only patch + independent readback; share diff, SHA and QA summary. Replace the current Library file **only when the coach expressly requests that file update**, using its stable Library ID, observed version, optimistic-concurrency version check, readback and rollback copy. Do not overwrite a published TrainingPeaks plan or an athlete calendar.
5. Update only the workstream checkpoint when reaching a meaningful gate, or the Decision Log if an actual method decision changed. No mandatory Core/Master/Open duplication.

## CLI

```bash
python scripts/ironman_jobs/ironman_xlsx_patch.py inspect --input source.xlsx --week W16 --term '6×1'
python scripts/ironman_jobs/ironman_xlsx_patch.py preview --input source.xlsx --manifest change.json
python scripts/ironman_jobs/ironman_xlsx_patch.py apply --input source.xlsx --manifest change.json --output test-copy.xlsx --report qa.json
```

Example **synthetic** manifest (not an instruction to change the production workout):

```json
{
  "schema": "IRONMAN_XLSX_PATCH_V1",
  "input_sha256": "THE_ACTUAL_64_CHARACTER_SOURCE_DIGEST",
  "scope": {"resource": "xlsx", "product": "CHASING_THE_SLOT_24W", "week": "W16"},
  "expected_route": "A_LOCAL",
  "changes": [
    {"sheet":"BICI QUALITA 24W", "cell":"J22",
     "before":"exact pre-edit full cell string",
     "after":"exact revised full cell string"}
  ]
}
```

For synchronized text edits, include all mirrored `sheet` / `cell` pairs. Optionally add `assertions: [{"sheet":"...","week":"W16","contains":"old phrase","before_count":1,"after_count":0}]` so an unmodified mirror fails QA.

## Verification performed 2026-10-21

Source copy: `CHASING_THE_SLOT_24W_CRUSCOTTO_VERDE_v14_QUADRATO_TEST_VO2.xlsx`, Library ID `libfile_d6acf69ed5308191819cd0573e150cef`; source SHA256 `17e16fcb26a6a35b8ccf365a7b4ff826dc66861a1a9773c8fbca9967221f6e6b`. In this source, 22 sheets, 2 chart parts and **1,766 actual formula XML nodes** were counted (the existing Product Card reported 1,763; this difference does not affect the equality check). The original input checksum was unchanged after tests.

- One cell: 1 cell / 1 sheet / 1 modified XLSX part, approximately 0.5 s for preflight, write and full readback.
- Synced text: 5 cells / 4 sheets / 4 modified parts, approximately 0.6 s.
- HI bike dose 6×1′ → 8×3′: `B_BLOCK_REVIEW_STOP` before any write.
- Numeric planned duration 140 → 170 in a linked source cell: `TEXT_ONLY_V1` stop.
- Mismatched source SHA256: `SOURCE_HASH_DRIFT` stop.
- Synthetic regression: 8 offline automated tests PASS including changes to intensity words without numerical change and preserving one test chart.

These measured times are local Python execution times, **not** timings of connector discovery/Drive/Library operations. The code and tests can execute independently of the current conversation. GitHub CI and a fresh-chat end-to-end behavior are distinct acceptance gates and should not be claimed as passed unless they actually run.
