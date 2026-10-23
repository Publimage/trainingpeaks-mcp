# IRONMAN — Unica interfaccia operativa, nessun job dedicato al singolo piano

Status: ARCHITECTURE CONTRACT / NOT DEPLOYED. This is not an authorization to retry a denied operation. Source of truth is Google Drive IRONMAN KNOWLEDGE BASE (00 Core, 00B Emergency, 00C Proven Paths, 11 Agent Orchestration Roadmap).

## Objective

One coach request -> one durable Prefect flow -> typed, plan-scoped operations -> provider readback -> one verified report. The same operations must handle every Training Plan ID. Stop creating one-off Python scripts or registry entries for individual workout IDs, weeks, notes or PDF filenames.

## Existing components: reuse, do not replace

- Prefect 3 process worker at ironman-prefect-staging: existing one-off CSS deployment PROVES worker flow execution, not yet general batch/write execution.
- TrainingPeaks MCP server: official authenticated account/provider access and existing tools; **not** a duplicate connector.
- Existing revision-pinned `tp_ironman_operator`: one safe fixed-job execution gateway, global filesystem lock and durable write receipt. Its current diagnostic fixes are generic for every existing registered job.
- `reviewed_plan_patch_preview` and `reviewed_plan_patch_publish`: approved in-place classic workout adapter for any Training Plan, with before/after manifest.
- Existing native notes and attachments provider paths in Proven Paths; note/PDF adapters must preserve the note ID and all unrelated attachments.
- Native StructuredStrength and Library tools: distinct typed adapters (different provider schemas), SAME orchestration entrypoint.
- Existing SQLite ledger on the TP server is a pilot; adopt/migrate to a durable Prefect task ledger rather than competing ad-hoc tracking systems.

## Single request contract (future public control plane)

```json
{
  "schema": "IRONMAN_CHANGESET_V1",
  "request_id": "unique-idempotency-key",
  "owner_id": 2116886,
  "targets": [{"kind": "training_plan", "id": 684602}],
  "changes": [
    {"kind": "plan_workout_description", "resource_id": 3996872965, "before_sha256": "...", "after_sha256": "..."},
    {"kind": "plan_note_attachment_retire", "resource_id": 2653899, "attachment_id": 95193, "before_sha256": "..."}
  ],
  "approval": {"status": "approved", "scope": "explicitly-reviewed-scope"},
  "baseline": {"plan_visibility": "public", "workouts": 259, "notes": 35}
}
```

This is a schema illustration, not a request to perform the displayed changes. Content or file bytes reside in a separately reviewed manifest, never raw commands.

Typed adapters (not one-off scripts) handle: classic plan workout patches; native Calendar Notes; note PDF add/retire; plan-native StructuredStrength relocation; Workout Library edits. Athlete calendar is a separate explicit scope. Every adapter must be reusable for multiple independent IDs and plans.

## Generic workflow lifecycle

1. Identify target through canonical Product Card, Drive decision and provider live read. Reject stale assumptions.
2. Validate approved scope, account owner, provider resource kind, expected before-image/fingerprint, public/price invariant, and change-set uniqueness. No write in preview.
3. Acquire a **resource-level lease** (provider account/plan/note ID). The existing global operator lock still protects shared git checkout. Prefect may queue, not bypass either lock.
4. Version resolution: read branch tip; if it moved due to an **independent** commit, compare changed paths and revalidate the preview at the new revision. Same-path conflict -> block only affected task. Never silently repin code reviewed for another scope.
5. Execute only the existing approved adapter. On ambiguous write or explicit security/authorization denial: READBACK and STOP that exact operation. Never rotate tools/credentials to bypass a denial.
6. Compare all preserved fields, counts, IDs, native structures, attachments, title, price and visibility. Commit `DONE_VERIFIED` only after provider readback.
7. Record receipt: `request_id`, target identity, manifest SHA, reviewed revision, resource lock, provider IDs, timestamps, result, checksum, failure code and readback fingerprint. No secrets.
8. Continue independent tasks in the dependency graph after a local failure; protect dependent tasks. Resume from the durable ledger; never duplicate completed writes.

State vocabulary: `PENDING`, `PREFLIGHT_PASS`, `RUNNING`, `DONE_VERIFIED`, `BLOCKED_SECURITY`, `BLOCKED_CONFLICT`, `FAILED_REVIEW`, `UNKNOWN_NEEDS_READBACK`. Reconcile `UNKNOWN` before any retry.

## Failure handling standardized

- `OPERATOR_BUSY`: wait/queue until lease releases. Do not treat as a provider/authentication error.
- `REVISION_DRIFT`: compare git delta and refresh reviewed pin only for independent changes, then new preflight.
- `WORKTREE_DIRTY`: stop server checkout mutation; separate repository worktrees per orchestration worker.
- `WRITE_RECEIPT_EXISTS`: read provider and receipt, never blindly retry.
- `JOB_SCRIPT_FAILED`: inspect job-specific safe stage and provider state, not "TrainingPeaks unavailable".
- External safety denial: cannot be retried/bypassed; record blocked task and continue permitted independent tasks.

## Rollout gates, never skip

A. Build on a feature branch; offline tests and read-only preview only. No live write to remediate a previously denied operation.

B. Integrate a single Prefect entrypoint with reviewed adapter interface; verify resource lock, crash recovery, Git revision collision, dedup, readback and cross-plan isolation on mock providers.

C. Canary on explicitly approved disposable plan; check power-loss/timeout scenarios without duplicate writes.

D. Extend to approved live plans; verify the full release on TrainingPeaks and canonize in Drive only after readback.

E. Deprecate per-workout and per-PDF one-off jobs only after coverage parity, without removing historical provenance.

## Non-negotiable

Prefect is the orchestration platform; do not invent a new homegrown scheduler or remote shell gateway. An adapter difference is normal, a new script for each individual edit is not. New feature work should use the common manifest, not append another 8-line job to `data/ironman_operator_jobs.json`.

## Implementation checkpoint — 2026-10-22, PR 18 (offline CI PASS)

The reviewed branch now includes a typed change-set engine, a generic READ-ONLY TrainingPeaks resource gateway for classic plan workouts, native Calendar Notes (and PDF attachments), native StructuredStrength and Workout Library items, and one Prefect flow named ironman-unified-changeset-v1.
Resource IDs are data rather than hard-coded scripts. On resume, a DONE_VERIFIED ledger item is rechecked against the provider before its state is reaffirmed. Explicit security denials are never retried through another route.

## Critical cross-host boundary

The new gateway uses TPClient credentials and therefore can run only on the authenticated TP-MCP runtime. The separate Prefect staging worker does NOT have coach TP credentials and must not receive them. The existing limited CSS private bridge is not a universal plan/resource read gateway.

Before deploying the common Prefect flow on the staging worker, separately review a READ-ONLY, resource-scoped private VPC bridge to the TP-MCP host, with exact owner, resource identity, caller/IP allowlist, no redirects and bounded payload. Alternatively execute read adapters on the TP-MCP host through a reviewed, typed worker. No arbitrary shell or broad credential forwarding.

Publishing is intentionally disabled: the Prefect flow rejects mode=publish before any provider access. Write-capable adapters must be integrated ONCE per resource kind, with existing Proven Paths, official endpoints and individual disposable-plan canaries. This does NOT authorize a previously denied PDF deletion or swim description change.

Prefect's local SQLite resource claim is not a distributed lock. Before any real multi-host publishing, every writer must also respect the existing TP-host operator lock; uncertain provider writes require readback before release of claims.

## Verified and pending

CI now runs the existing operator suite, the generic change-set/idempotency suite, synthetic TrainingPeaks read tests for all resource kinds, and a live local Prefect flow over a synthetic provider. This demonstrates code integration, not an authenticated end-to-end TP operation.

CI uses prefect==3.8.8 and fastapi<0.155 to avoid a backward-incompatible FastAPI Body(min_items) removal. This is dependency pinning, not a TP failure.

Still OPEN: controlled private-bridge read access, dedicated staging work-pool smoke test, shared multi-host write lock, review of reusable write adapters per type, crash/dedup canary on approved disposable plan, production release gate.


## 2026-10-23 — Reusable note-PDF retirement typed adapter

The same typed operation `plan.note.attachment.retire` is now represented by `scripts/ironman_jobs/ironman_unified_note_pdf_adapter.py`. The code accepts a reviewed plan ID, note ID and PDF attachment ID as manifest data; it does not contain an Intermediate/CHASING-specific target. `validate_pdf_retirement` checks the full before/after native Calendar Note, filename and byte count, rejects attempts to change other note fields or attached files, and uses the already-proven 2026-10-19 provider DELETE route with `_retry_on_401=False`. A single change-set can contain sequential PDF removals on one note or independent operations on different plans. The existing ChangeSet ledger provides serialization, duplicate detection, readback and ambiguous-outcome handling.

Crucial distinction: this adapter is **not registered as a live writer** in the Prefect preview flow; `delete_one=None` by default is a hard stop. Code review, current CI and a disposable-plan writer canary remain separate gates; neither PR #18 nor the previous Intermediate-specific cleanup publisher becomes permission to bypass a denied provider operation. The old per-plan scripts are historical compatibility paths and must not be cloned for each subsequent plan. Source of policy and Proven Path remains Google Drive 00C.

Offline adapter smoke executed 2026-10-23: two distinct synthetic plans use the same adapter, exact PDF removed and unrelated PDF preserved; unapproved note rewrite rejected; default writer disabled. `tests/test_ironman_unified_note_pdf_adapter.py` adds integrated engine tests for cross-plan parity, two sequential deletions, drift and partial/uncertain results; independent CI for the current commit is **not yet verified**.
