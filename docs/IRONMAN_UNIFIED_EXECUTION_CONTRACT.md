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
