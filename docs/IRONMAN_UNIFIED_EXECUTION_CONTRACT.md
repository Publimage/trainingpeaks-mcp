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
execution): **52 pytest tests passed in 0.55 seconds** on the engine, PDF adapter, classic plan adapter, TrainingPeaks read gateway,
and all existing `plan_patch_batch_core` validator regressions. All provider
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


## Audit di sicurezza e continuita' — 25/10/2026 (PR18, non deploy)

INCIDENTE RISOLTO: WINTER FOUNDATION plan 689369 ha gia' 58 descrizioni/45 titoli pubblicati e readback indipendente 58/58. E' una operazione WORK_COMPLETE, NON un canary da ripetere. Il branch trusted contiene il suo manifest reviewed ormai storico.

Il publisher classic ha un percorso live verificato. La PR18 non lo sostituisce e non deve essere distribuita finche' i gate di CI, VPC, lock e adapter non sono superati. Sono ora distinti: (i) target_plan_id della richiesta corrente; (ii) request_scope corrente; (iii) requested_workout_ids correnti. Per il publisher classic candidate PR18, tutti e tre devono essere supplied da caller independently e combaciare con il payload reviewed. Questa difesa blocca non soltanto Intermediate684602 vs WINTER689369 ma anche un nuovo task su WINTER689369 che incontrasse il manifest dei 58 gia' completati.

Nel motore universale: un SKIPPED_DEPENDENCY storico diventa recuperabile PENDING; un DONE_VERIFIED non riconfermato sul provider non puo' sbloccare i dipendenti; letture temporaneamente non disponibili non annullano operazioni indipendenti; risultati PREVIEW_ONLY/ACTION_INCOMPLETE/WORK_COMPLETE separati. L'engine universale accetta requested_targets con provider/owner/container/resource IDs indipendenti e disabilita ogni publish.

Correzioni di sicurezza nella stessa PR: il bridge privato redige token, header Authorization e Cookie nei receipt amministrativi; l'output dell'operatore riusa lo stesso redactor; i readback StructuredStrength conservano anche prescribedDurationInSeconds, indispensabile per la verifica della dose. Test di regressione aggiunti nei file esistenti, inclusi test_reviewed_plan_patch_pipeline.py e test_private_bridge.py.

VERIFICA DISPONIBILE: 47 test offline isolati su QUATTRO funzioni pure identiche alla sorgente GitHub (controllo CRC32 sorgente) eseguiti in container, 47 PASS; includono casi positivi/negativi di request scope, workout ID, target resource e redazione di sei valori fittizi. Queste prove NON corrispondono alla suite pytest di tutto il repository, al workflow GitHub Actions, a un collaudo reale Prefect/VPC o a una scrittura TrainingPeaks. Il repository privato non e' materializzato nel container, il runtime locale non ha Prefect e la CI GitHub sul nuovo HEAD non presenta run. Un mergeable Git clean non sostituisce CI e staging. Non effettuare merge, deploy, enable writer o update di TrainingPeaks in questo stato.

NEXT GATE documentati nella Knowledge Base corrente: 21_TRAININGPEAKS_MCP_INTEGRATION_STATE e 03_OPEN_QUESTIONS_ROADMAP. Le autorizzazioni della richiesta originale non sono una autorizzazione a pubblicare altri workout o a cambiare configurazioni dei servizi attivi.


## Canonical outcome requirement — dynamic discovery from any authorized chat (2026-10-25)

The coach explicitly requires **one persistent TrainingPeaks execution capability usable from any ChatGPT conversation with the connected tool and necessary account permissions**. The engine must accept a NEW coach instruction referring to ANY accessible, supported TrainingPeaks athlete, Training Plan, Workout Library or workout, even if none of those objects has ever appeared in this repository, the Knowledge Base, an old manifest or a canary allowlist. Existing tests, manually configured IDs and preverified workouts are evidence/examples, NOT the set of objects the engine can process. No per-plan registration, GitHub commit, per-workout script, new Prefect deployment or manual configuration change for routine supported requests.

The existing WINTER 689369 manifest was merged into the PR only to preserve the trusted branch's historical, already-published data and avoid a git conflict. It is NOT a seed catalogue, default target, permanent allowlist or recurring publication payload. Never select a new request from it or replay its 58 published changes.

**Separate three things:**
1. Code/proven adapter revisions: versioned, tested and approved ONCE per operation class (plan create/copy/edit, workout create/patch/transfer, native Strength, Notes/PDF, Library, athlete calendar). This is a capability catalogue, not a registry of allowed plan/workout IDs.
2. Provider resource discovery and authorization: after the coach's NEW request, query TrainingPeaks through the existing authenticated MCP runtime, resolve coach/athlete association, object type, owner, plan/library ID and current revision; respect actual provider permissions and any explicit external security denials. If names are ambiguous, stop for disambiguation. The provider account must really be able to access/modify the target.
3. Immutable change request: generate IRONMAN_CHANGESET_V1 internally from current intent + live provider facts, with a unique request_id, narrowly scoped operation, exact resolved targets, review/approval proof when needed, before/desired state and per-resource receipt. This request object is created automatically in durable storage; it is **not** an editable singleton file committed to GitHub for every user request.

The static server-local allowed_unified_reads resource_ids policy is a **staging-only deny-by-default control**. It MUST NOT be interpreted as the feature specification for routine operation: it currently prevents new resources from being handled without manual server configuration. Production-grade generalized reads require an independently reviewed, trusted resource-discovery/authorization design (for example, server-issued short-lived request-scoped capabilities for discovered IDs, with authorization independently checked on the TP host), with an explicit approved security model. Do not remove, widen, bypass or silently replace the current staging allowlist before that design has passed security review and tests. No arbitrary URL, account, command, shell, provider API proxy or credential forwarding.

The current PR18 engine only supports six existing-resource operation kinds and requires positive existing resource_id/container_id values. It DOES NOT implement create-new-plan, create-new-workout, publish-to-athlete-calendar, dynamic discovery, request-scoped server-issued authorization, or full writer functionality. Never describe it as end-to-end universal until these missing classes are built and proven through their individually authorized native adapters. New-resource operations need typed CREATE steps with before=ABSENT, collision/dedup checks, provider-assigned IDs read back and recorded durably; dependent steps refer to the newly verified ID. Athlete calendar and dated assignments are separate from dateless Training Plan week/day positions.

**Acceptance scenarios required before calling this general-purpose:**
- A fresh chat requests an edit to a previously unseen private Training Plan whose ID is not in any test file or allowlist; the system resolves it live, obtains valid scope and completes only the approved operation with provider readback, without code/manifest/server-config edits.
- Another fresh chat creates a new workout (or plan) in a supported permitted destination that has no pre-existing workout ID, obtains the provider-generated ID, then verifies the whole result. No manual template upload or GitHub action.
- Coach chooses an athlete by name; identity/relationship is read back and independently bound to the correct athlete calendar. An ambiguous name, other athlete or different plan must STOP, not guess or use the last selected target.
- Repeat the same request_id after partial failure: no duplicate workout/plan, no cross-plan spill; re-read provider before retry. An explicitly denied operation stays blocked.
- Previously verified Library templates may be reused as optional content sources but are never mandatory prerequisites for a new prescription. Apply discipline-specific coaching/naming/builder QA and approval gates to newly generated training content as usual.
- One single shared tool and runner entrypoint from different chats, with state/receipts in the service and canonical decisions in Google Drive, independent of chat history.

Status: **PRODUCT REQUIREMENT / NOT YET IMPLEMENTED**. Keep PR18 draft, preview-only and its current allowlists unchanged; keep the proven live adapters for their authorized scopes. No PR18 merge/deploy or provider writes authorized by this requirement.



## 2026-10-26 - Durable preview boundary (PR18 source-only)
Status: SOURCE-INTEGRATED / NO FULL CI / NO PROVIDER WRITES. PR18 remains DRAFT.

The request is immutable and persisted once in DraftStore. Each passing preview_draft
runs against a temporary in-memory SQLite Ledger, so it cannot claim or poison
the future execution ledger under the same request_id. Passing read-only
provider observations are persisted as separate immutable preview revisions
in the existing DraftStore database (request_id + preview_sha256). A new
observation yields a new preview ID; re-reading the same snapshot reuses it.
Failed/conflicting previews are returned to the caller but not persisted as
approved-looking snapshots.

The preview record contains a reviewed ChangeSet manifest and its read-only
receipt. It is NOT an approval token, does not grant provider permissions,
does not enable unified publish, and cannot substitute a provider canary. The
store checks manifest hashes, PREVIEW_ONLY scope, zero provider writes, and
passing item results. get_preview can recover one exact immutable revision
across chat rollovers; the active tool surface does not yet expose a generic
user-facing retrieval method. A changed desired operation requires a new
immutable request identity rather than silently mutating the old draft.

Source as of commit 139e8b93a3bb8e29ca1ec590357c365eb1bfdb68:
scripts/ironman_jobs/ironman_unified_prefect_flow.py and
scripts/ironman_jobs/ironman_dynamic_request_store.py; test cases in
test_ironman_unified_prefect_flow.py,
test_ironman_dynamic_request_store.py and
test_ironman_dynamic_prefect_isolated.py. CI/run status on exact HEAD must
be checked before release; individual new tests have not been certified by
GitHub Actions. The separate publish/approval model and true provider
writer adapters still require authorized implementation and live canaries.


## 2026-10-26 - Resume an immutable preview across chats (source-only)

The existing `ironman-unified-changeset-v1` Prefect entrypoint has a read-only
`mode=resume_preview`; it does NOT add a new job or publishing path.
The input has exactly `schema=IRONMAN_PREVIEW_RESUME_INPUT_V1`,
`request_id`, `preview_sha256`. The caller also provides the independently
resolved `requested_targets` for the current chat. The flow reads the
immutable draft and exact stored preview from `IRONMAN_OPERATION_DRAFT_STORE`,
validates the saved ChangeSet and stops if the current target list differs.
It returns the stored preflight results with `request_state=PREVIEW_ONLY`,
`provider_writes=0`, `publication_enabled=false` and
`source=stored_read_only_preview`. A stored preview is NOT a live recheck,
not an approval and not an authorization to publish. There is no provider
read/write in this resume mode; a fresh preview is required for fresh provider
facts. This endpoint has not been deployed or exposed through a general live
ChatGPT tool yet.

GitHub implementation commits: `238b25959237f7df998e95c1eee62ac657cdc985`
(flow) and `f03eb87af081d51321b8b8067898e626090952c9`
(regressions). Offline exact-source QA: seven tests pass on the exact Prefect
flow source blob `0dbb72d41c41609ed97185c45296ad1737ca0807`
with a stubbed private store/Prefect/provider. This is NOT full repository CI,
not a test of the real DraftStore, not a deployment and not a TrainingPeaks
writer canary. Remain DRAFT/preview-only until gates are satisfied.

## Draft / preview / approval / execution lifecycle — source integrated, not released

Canonical policy: Drive 02_DECISION_LOG, architectural anti-patch decision of
2026-10-26, and 21_TRAININGPEAKS_MCP_INTEGRATION_STATE. Reuse the existing host,
Prefect entrypoint, typed adapters, SQLite stores and Proven Paths. No new job,
per-plan manifest, infrastructure, provider write or deployment in this segment.

### Common contracts

`ironman_operation_contracts.require_target_binding` is the selector contract
for both flow and Approval: exactly one selector per kind/resource, independent
of order. Two ordered edits of the same kind/resource use one selector, not two.
Operation identity and ordering remain explicit in ChangeSet item IDs/dependencies.
DraftStore ingress and resume now use shared receipt and draft-binding validators;
validation still runs at both trust boundaries. The immutable draft, preview hashes
and execution manifest format are preserved.

### Control operations in the existing flow

`ironman-unified-changeset-v1` supports `approve_preview`, `revoke_approval` and
`bind_execution`, alongside prepare/preview/resume. Input is
`schema=IRONMAN_REVIEW_INPUT_V1`, request_id, preview_sha256, reviewed_revision,
approval_scope; revoke/bind also require approval_sha256. Independently resolved
requested_targets remain separate. No caller-supplied principal, authorizer,
module path or callback is accepted in this serialized input.

The flow resolves and validates the stored preview and exact selectors, then
consults the trusted host's `get_review_authorizer().authorize(command)` for EVERY
control action. The command includes the action, preview manifest, review input
and requested targets. Only literal True permits mutation. The production
provider is deliberately unconfigured and denies by default; host authentication,
current grants/expiry/revocation and actor audit must be implemented behind this
boundary before it is enabled. Test authorities are synthetic, not live identity
verification. There are no bearer secrets in these flow inputs.

Approval records remain immutable and are bound to request, exact preview
(including its observation), reviewed revision and scope. Retrying reuses them.
SQLite transactions serialize approval, revocation and execution binding.
Revocation creates a monotonic tombstone: an old decision cannot be resurrected
by approve or bind, including after reopening or after an earlier binding.
This cancels future authorization, not an already in-flight provider request.

bind_execution reserves exactly one approval/manifest per request; it never opens
an execution ledger or invokes an adapter. New observations or code revisions do
not inherit approval. Publish is still rejected unconditionally by this flow.

### Enforcement at the execution engine boundary

`run_changeset(execute=True)` now also REQUIRES a trusted `authorize_execution`
callable. Matching scope/revision strings alone are insufficient. The engine
checks authority at entry and before each write, passing defensive copies;
denial or failure is fail-closed. Existing readback, uncertainty and explicit
provider-denial behavior remain in the same engine. Test callbacks accepting
synthetic execution are explicit; no production permissive implementation exists.

`BoundExecutionAuthorization` is the shared reusable guard for a future reviewed
writer: match the candidate manifest to the persisted preview, ask the trusted
authority, then re-open/revalidate the persistent binding and revocation. Its
constructor context must come from the trusted coordinator. The guard is tested
with a revocation between two dependent synthetic writes; the second is blocked.
The current flow never calls execute and never installs this guard on live writers.

### Worker coordination and recovery

The execution ledger owns a single persistent worker slot with an invocation UUID,
not a request ID. Acquisition is atomic; a second connection/process cannot enter
provider execution even with the same request ID. Whole executions are serialized
on this existing shared ledger; previews do not reserve a worker. Normal exit
releases only the acquiring invocation's slot. A process crash leaves it blocked;
there is no expiry, blind retry or automatic takeover. Existing item/resource
claims and post-crash readback remain authoritative for uncertain outcomes.

All workers must use the same configured service ledger. Independent local SQLite
files are independent coordination domains, not a distributed lock. A future
release must enforce this topology and test it on the actual runtime; these tests
do not attest cross-host coordination or network-filesystem SQLite safety.
Authorized recovery must first establish quiescence and independently reconcile
provider/item state before clearing an orphaned slot. No recovery endpoint is
exposed or enabled by this change.

### Debt and release gates

Owner below means the Operator component maintainer, not the coach/user.
No feature is WORK_COMPLETE while an applicable gate remains open.

| Classification | Item and reason | Target / removal condition | Verification |
| --- | --- | --- | --- |
| STRUCTURAL_REFACTOR — addressed | Divergent flow/Approval selectors and duplicate preview validators could drift | Shared selector and preview validators now used at both boundaries | Same-resource chain, corrupt records, existing regressions |
| STRUCTURAL_REFACTOR — addressed in one-ledger domain | Replaying request identity was not worker ownership | Invocation-owned persistent execution slot | Concurrent connections, resumed execution, dead process |
| MISSING — release blocker | Trusted authority is intentionally unconfigured | Wire authenticated host identity, current grants/expiry/revocation and actor audit behind the existing authority interface before enabling control operations | Runtime authentication, deny/expiry/revocation integration tests; default deny must remain |
| MISSING — release blocker | Crash slot recovery has no approved operational endpoint | Add authorized quiescence + readback recovery in the existing service before live execution | Dead-owner recovery, active-owner refusal, no duplicate writer |
| MISSING — release blocker | One-ledger topology is not deployment-attested | Enforce a single canonical service ledger for all workers before live execution; no arbitrary per-request ledger paths | Real-runtime multi-worker canary and readback |
| TEMPORARY_DEBT | Classic adapter constructs FIELD_VALIDATION_ONLY manifest to reuse proven validation | Owner: Operator maintainer. Extract pure field validation shared with existing publisher before final release; remove synthetic manifest | Equivalent Builder/field rejection and adapter/publisher regressions |
| TEMPORARY_DEBT | SKIPPED_DEPENDENCY legacy recovery branch lives in normal execution | Owner: Operator maintainer. Replace with versioned migration after archived ledger inventory, before final release; remove branch once migration verified | Migration preserves receipts, dependencies and denials |
| TEMPORARY_DEBT — QA only | Partial exact-source snapshot used because git proxy is unavailable and Prefect is absent | Owner: Operator maintainer. Replace with complete pinned checkout and actual Prefect tests before release; discard isolated harness | Full repository/Prefect CI on exact commit; isolated PASS never substitutes |

Existing staging VPC allowlists and capability guards remain in place. Their
replacement requires request-scoped authorization review, negative scope tests
and authorized canaries; no policy removal or widening is part of this change.
Workflow edits and plan_mutation_gates changes previously denied remain excluded.
The old proven publisher remains scoped and untouched; no claim of live readiness.
