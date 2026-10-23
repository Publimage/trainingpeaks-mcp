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

The ONE existing schema is `IRONMAN_CHANGESET_V1`. Do not invent a
different manifest for a specific plan. Example *shape only*, intentionally
non-executable (hashes and IDs below must come from a real reviewed readback):

```json
{
  "schema": "IRONMAN_CHANGESET_V1",
  "request_id": "example-revision-001",
  "owner_id": 2116886,
  "reviewed_revision": "<reviewed 40-character Git SHA>",
  "approval_scope": "approved:exact-operation-scope",
  "changes": [
    {
      "id": "retire-one-pdf",
      "kind": "plan.note.attachment.retire",
      "target": {
        "provider": "trainingpeaks",
        "owner_id": 2116886,
        "container_kind": "training_plan",
        "container_id": 777001,
        "resource_id": 777002
      },
      "before_sha256": "<digest of complete original provider Note>",
      "after_sha256": "<digest of complete Note after one PDF removal>",
      "depends_on": [],
      "payload": {
        "desired": {"id": 777002, "planId": 777001, "attachments": []},
        "attachment_id": 777003,
        "expected_file_name": "obsolete.pdf",
        "expected_content_length": 12345
      }
    }
  ]
}
```

The shown `desired` object is deliberately incomplete; a real approved
manifest must contain the entire original provider Note unchanged except for
exactly one attachment. No source code or plan-specific job changes when the
IDs change. Two removals on one Note must declare a direct dependency and two
exact successive before/after images. The integrated preview validates both
steps using a virtual intermediate state, without altering TrainingPeaks.

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


## 2026-10-23 — Cross-plan regression and capability status

Code path: PR #18 `fix/ironman-unified-operator-errors-20261022`. The
existing read-only registry now injects validation adapters for
`plan.workout.patch` and `plan.note.attachment.retire`; the other four
ChangeSet kinds continue to use the shared read-only adapter. This is one
typed router, not one job per plan. The proven classic field validator
`plan_patch_batch_core.validate_manifest` is reused for plan workouts;
the proven attachment DELETE route remains one guarded callback per reviewed
operation, disabled by default.

Actual independent local verification (GitHub blob hashes compared before
execution): **39 pytest tests passed in 0.56 seconds** on the engine, PDF
adapter, classic plan adapter and TrainingPeaks read gateway. All provider
objects were synthetic; TPClient imports were isolated by local stubs.
Covered: two distinct plan IDs using the same adapter, two sequential PDF
removals with clean preview, 100% unrelated-field preservation, rejected
unauthorized fields, deliberate denial, no-writer default, crash RUNNING
receipt readback, timeout, lost readback, idempotent full-chain restart.
No provider write, calendar or production-plan change occurred.

**Separate gates:** the latest GitHub Actions run matching the new PR head has
NOT been observed; old green CI results are not proof for these commits.
Full Prefect/private bridge integration suite NOT run in the local environment.
PR remains DRAFT / NOT MERGED / NOT DEPLOYED, and the unified flow remains
preview-only. Callback injection in unit tests is NOT provider-write approval.
Actual live writer paths still route via the scoped previously verified Proven
Paths, not a generic unrestricted ChatGPT write tool.
