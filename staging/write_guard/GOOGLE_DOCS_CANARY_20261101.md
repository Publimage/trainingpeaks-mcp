# Google Docs connector contract canary — 2026-11-01

Status: **PASS for the provider request contract; NOT an end-to-end Write Guard deployment.**

An ephemeral, explicitly isolated native Google Doc was created through the authenticated Google Drive connector. Its title identified it as a disposable sandbox. It was the only document modified in this live canary; Knowledge V1, V2, TrainingPeaks, Facebook, GitHub and DigitalOcean were not modified by this test.

## Sequence and evidence

1. Created a native Google Doc (sandbox) and retrieved its actual document ID, `t.0` tab and revision through `get_document`.
2. Inserted `CANARY_SOURCE_20261101` with `batch_update_document` and the initial `write_control.requiredRevisionId`. Result: success; fresh revision.
3. Read back the same document and found exactly one source marker.
4. Used `replaceAllText` with `matchCase=true`, `tabsCriteria.tabIds=["t.0"]`, and the fresh `requiredRevisionId`, replacing it with `CANARY_FINAL_20261101`. Provider returned `occurrencesChanged=1` and a new revision.
5. Submitted an independent deliberate stale-revision mutation with the preceding revision; Google Docs rejected it with HTTP 400 `INVALID_ARGUMENT`: `required revision ID does not match the latest revision`. This is an expected precondition failure, **not** a security denial.
6. Final readback found exactly one final marker and no stale-test mutation. No repeat of the rejected request.
7. Deleted the disposable sandbox. `get_file_metadata` returned `NOT_FOUND`, confirming its absence.

## What this proves

- The authenticated Google Docs connector honors revision preconditions for a targeted update.
- The targeted replacement can return a single replacement count and readback confirmation.
- A stale revision fails without modifying the document.

## What it does not prove

- The local Python `DocsWriteGuard` has **not** been wired into the authenticated connector or deployed as a server-side enforced gate.
- `google_docs_adapter.py` is an injected transport adapter with offline contract tests; it was not loaded into the live connector process.
- Credential separation, independent authorizer, force-all-writes routing, multi-host persistence, observability, and rollback are not production-verified.

Next gate: review provider bridge and authorizer and run the **entire** Write Guard + Google Docs adapter against an approved disposable document, then restrict bypass permissions before describing the guard as enforced.
