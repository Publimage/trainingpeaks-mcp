# ADR-001 — Capability-based Write Gate and Release Contract

Status: PROPOSED / OFFLINE-POC TESTED (2026-11-01). Owner: IRONMAN coach approval required for live rollout.

## Context

The Knowledge V2 router is effective at retrieving historical and current state but cannot force a model to use the correct write path. Existing V1 00C Proven Paths describe tested procedures, not machine-enforced authorization. The objective is to prevent predictable failures without introducing a new permanent blocker due to missing one-off path certification.

## Decision

1. **Capability-first**: match provider, resource and operation type against a trusted registry. Reuse one verified class across multiple authorized objects. A missing new class initiates validation/canary, not a global system stop.
2. **Provider-specific policy**: actor grants are verified by the service, are separate from Proven Path verification and are bound to the complete intended delta. TrainingPeaks and Facebook do not inherit Google Docs semantics.
3. **Preflight then mutation then readback**: target, immutable operation ID, revision, identity/approval, invariants, provider CAS, durable journal, postcondition. Report success only with provider evidence.
4. **Persistence before side effects**: maintain an auditable state machine in a durable ledger. After an interruption, reconcile provider state before taking another action.
5. **Respect security boundaries**: a confirmed security denial cannot be retried through another route or reformulated to circumvent it. Failures in one capability do not block independent valid work.
6. **Rollout**: use a narrow provider adapter first. Keep both read-only and write privileges minimal. Deny uncontrolled alternate write channels only after owner approval and evidence that the approved workflow is reliable.
7. **Source of truth**: V1 Drive remains canonical until the coach explicitly approves promotion. Write ledger, CI and artifacts are operational evidence only.

## Acceptance gates (all required before production claim)

| Gate | Evidence required | Current |
|---|---|---|
| G1 unit tests | Negative tests including scope, forged content, stale revision, idempotency, security denial | PASS offline (31 tests total across suite) |
| G2 crash test | Real process exits before and after local fake provider mutation | PASS offline |
| G3 real provider adapter | Exact Docs API revision enforcement and readback | NOT DONE |
| G4 IAM/security | Independent identity, scoped authorization, no LLM self-certification, bypass restricted | NOT DONE |
| G5 staging integration | Live sandbox document, conflict/timeouts/crash and no duplicates | NOT DONE |
| G6 resiliency | Restore/restart and cross-process/multi-host coverage for target topology | PARTIAL, only one-host POC |
| G7 deployment controls | Reviewed PR, CI on exact SHA, security tests, rollback plan | NOT DONE |
| G8 real observability | Reconciled vs unreconciled operations; coverage vs direct/bypass writes | NOT DONE |
| G9 new-chat recovery | Fresh session recovers same operation and verified status | NOT DONE |

## Defects identified during code review and addressed in v0.2

- Authorizer previously checked only target and operation ID in the fake. It now checks all substantive fields of the mutation in the fake contract; a real service remains necessary.
- SQLite previously recorded `STARTED` within the transaction containing the external call. An abrupt process death could discard that state. The POC now commits `IN_FLIGHT` before invoking the provider, and has actual child-process death tests.
- The capability resolution no longer requires a distinct named Proven Path per authorized document. It resolves the existing Docs class automatically.
- A racing read of an already verified operation is checked again before reporting an unexpected missing checkpoint.

## Unresolved engineering risks

A self-healing retry of a truly ambiguous provider mutation is impossible without validated provider idempotency, compare-and-swap semantics, or authoritative reconciliation. Availability is not the same as blindly retrying. The production design must make unknown-path onboarding automatic and safe, but never claim a new live capability is verified without real evidence.

## 2026-11-01 addendum — provider connector canary and v0.3 offline adapter

- Adapter: `google_docs_adapter.py` uses an injected official connector interface (`get_document`, `batch_update_document`) with the Google Docs API request shape. It requires a tab ID and paragraph-only content, rejects non-text/tables and mismatched document identity, sends `write_control.requiredRevisionId`, and checks `replaceAllText.occurrencesChanged=1`.
- Tests: 43 local tests PASS (31 prior + 12 new contract/integrated-fake checks). A fully authenticated **separate** Google Docs canary confirmed insert, targeted replace, stale-revision rejection, final readback and disposable document deletion. See `GOOGLE_DOCS_CANARY_20261101.md`.
- Scope: the canary exercised the connector directly; the Python guard and connector are not linked in one deployed runtime. Hence **G3 request contract: PARTIAL**, **G5 provider canary: PARTIAL**. G4 IAM, G7, G8, G9 remain unpassed.
- Proportional testing: high-risk authorization/state transitions get negative, crash and integration coverage. Small editorial or documentation updates use scoped check/readback, not repeated full-system audits.


## 2026-11-01 addendum — v0.4 authenticated bridge review

- **Implemented in source:** `GoogleDocsRestConnector` (Google REST contract, exact mutation type, requiredRevisionId, tab scope, status verification); `make_service_account_connector` (Google ADC with dedicated expected service-account identity, no user OAuth fallback); `SignedApprovalAuthorizer` (actor/whole-patch digest/expiry/HMAC) and `StandingPolicyAuthorizer` (trusted scoped approval, additive bounded checkpoints); `ScopedWriteService` (shared `DocsWriteGuard` durable ledger and explicit allowlist).
- **Negative testing:** wrong principal, mutation change after signature, expired/wrong/unsigned approval, foreign document, deletion, oversized patch, arbitrary URL, missing revision, explicit HTTP403 persisted and no retry, HTTP429 not misrepresented as success; 64/64 offline tests PASS.
- **Outstanding trust boundaries:** independent inbound caller authentication, service-side policy issuer/revocation, real ADC identity and resource ACL review, hosting and durable ledger recovery, a live full guard-to-Docs canary and postwrite readback, CI/review of exact SHA, and verified control of bypass paths. The ChatGPT Google Drive connector uses a separate authenticated connection; its token is not transferred to Python.
- **Go/no-go:** Source-level bridge review = ready for independent review; live integration = NOT READY; mandatory enforcement and production release = NOT APPROVED/NOT DEPLOYED. Do not ask the coach for a per-document certificate when a standing approved class already covers it; do not silently allow new high-risk operations without independent grants.
