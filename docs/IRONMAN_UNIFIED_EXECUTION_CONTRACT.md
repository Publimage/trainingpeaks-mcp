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

The existing workflow defines operator, change-set, synthetic reader and local
Prefect checks. Its presence is not evidence of a successful run on the current
HEAD; verify per-commit GitHub status independently. Local full-checkout results
are documented below and are not a TrainingPeaks/issuer production canary.

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

The reviewed batch publisher and the typed classic workout adapter share the pure
`plan_patch_batch_core.validate_patch_fields(before, after)` function. Plan title,
visibility, counts, owner and reviewed scope remain actual publisher metadata;
no synthetic FIELD_VALIDATION_ONLY manifest is constructed by the adapter.
Field validation does not select a target, mutate input or grant authorization.

### Versioned ledger migration

Ledger schema version 1 replaces the legacy SKIPPED_DEPENDENCY execution branch.
After independent execution authorization and worker acquisition, request identity
verification, migration and registration occur in the SAME SQLite transaction.
Every converted legacy event is copied in full to ledger_event_migration_backup;
only its live state changes to PENDING. Provider hashes, reasons, timestamps,
request digests, claims, DONE_VERIFIED, BLOCKED_SECURITY and uncertain states are
preserved. The normal dependency/preimage/readback checks then apply unchanged.

Preview and denied execution do not migrate. Rollback preserves both schema and
events; a mismatched manifest cannot migrate other requests. Version 1 is applied
once. Future/unrecognized versions, unknown states or legacy rows reintroduced
after migration are refused, not repaired ad hoc. New set_state calls cannot
persist SKIPPED_DEPENDENCY; that name remains a non-durable dependency-deferral
result. Explicit maintenance uses the same migration helper on a trusted,
quiescent host; no maintenance endpoint/job or live database migration is enabled
by the code change. Old and new worker versions must not share a ledger during
upgrade. Runtime migration/rollback must be rehearsed on an authorized ledger
snapshot before release; no production SQLite data was migrated during QA.

### Control operations in the existing flow

`ironman-unified-changeset-v1` supports `approve_preview`, `revoke_approval` and
`bind_execution`, alongside prepare/preview/resume. Input is
`schema=IRONMAN_REVIEW_INPUT_V1`, request_id, preview_sha256, reviewed_revision,
approval_scope; revoke/bind also require approval_sha256. Independently resolved
requested_targets remain separate. No caller-supplied principal, authorizer,
module path or callback is accepted in this serialized input.

The flow resolves and validates the stored preview and exact selectors, then
uses `get_review_authorizer().run_control(command, store)`. Identity verification,
current grant/revocation checks, the control mutation and actor audit share one
SQLite writer transaction. Nested DraftStore writes use savepoints, so an inner
commit cannot outrun a concurrent grant revocation. Failed mutations roll back.

The concrete `HostReviewAuthority` uses the existing cryptography dependency to
verify compact JWT assertions with host-pinned RS256 or EdDSA public keys. It
checks signature, pinned algorithm/key type, issuer, audience, subject, token ID,
required scope, iat/nbf/exp and an issuer-signed `run_id` against
the trusted Prefect context: FlowRunContext.flow_run.id for a flow, or
TaskRunContext.task_run.flow_run_id for a child task. Standalone tasks and missing
or ambiguous parent references are denied; task_run.id is never an origin substitute.
A valid assertion for another
invocation is denied; caller-supplied principal/context is never trusted. No
remote JWT key URLs, unsigned tokens, HMAC fallback or provider cookies are used.
The existing TrainingPeaks credential and VPC source IP do not authenticate a
review caller and are not repurposed for this role.

Host-only configuration is `IRONMAN_REVIEW_TRUST_CONFIG` (issuer, audience,
required_scope, pinned keys and administrator subjects),
`IRONMAN_REVIEW_ASSERTION_FILE` (private assertion for THIS scheduler invocation)
and the existing `IRONMAN_OPERATION_DRAFT_STORE`. Paths are never serialized flow
arguments. Files must be regular, private, owner/root-owned and not symlinks.
Trust configuration is reloaded and identity verified on every operation/check.
No signing key, issuer, account, listener or production credential is created.
The existing identity issuer/launcher must supply the signed invocation-bound
assertion; this upstream connection has NOT been configured or live-attested.
Missing trust, assertion or scheduler context denies by default.
Upstream token/account revocations must also reach the persistent token/principal
revocation API through that trusted host integration: offline signature validation
alone cannot discover an account disabled at the issuer. This live handoff is a
release blocker, not an assumed capability of the JWT verifier.

Exact-preview grants, grant/token/principal revocations and actor audit live in
new tables of the SAME DraftStore database, with indexed request bindings.
Grant issuance/revocation is host administration only: it requires a current
signed administrator identity pinned by host policy; no grant-creation tool or
flow mode is exposed. Ordinary callers cannot grant themselves permissions.
Grants are immutable, bounded by expiry and bind issuer/subject, request, preview,
revision, scope and manifest digest plus allowed actions. Removing/revoking a
principal's grant or its grantor is checked at every use. No live grant has been
issued by this work. The audit stores actor IDs, decision codes and command
hashes, not raw JWTs, private keys or command/provider payloads.

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
authority, then re-open/revalidate the existing persistent binding and revocation.
The guard never creates a binding or substitutes an execute grant for the distinct
bind_execution permission. The authority checks the exact approval/binding and
current grants/revocations in the same SQLite writer transaction. Its
constructor context must come from the trusted coordinator. The guard is tested
with a revocation between two dependent synthetic writes; the second is blocked.
The current flow never calls execute and never installs this guard on live writers.

### Worker coordination and recovery

The execution ledger owns a single persistent worker slot with an invocation UUID,
not a request ID. One shared POSIX file-lock primitive is reused by this engine
and the existing reviewed batch publisher. It protects the whole execution and
records its inode/protocol with the worker slot. Normal exit releases only the
acquiring invocation. Process death releases the kernel lock, but the durable
slot remains blocked pending explicit authorized recovery. No timeout/PID guess,
expiry, blind retry or automatic takeover is used.

The SAME Prefect entrypoint now supports `mode=recover_worker`, input
schema `IRONMAN_RECOVERY_INPUT_V1`, request_id, preview_sha256, approval_sha256,
reviewed_revision, approval_scope and the exact worker_owner nonce. Current
requested_targets remain independently checked. Recovery uses the host's
`IRONMAN_OPERATION_EXECUTION_LEDGER`; a different caller ledger path is refused.
Only the existing local/private_bridge read registry is used, after independent
recover_worker permission is verified. Recovery is never an execution grant.
A revoked approval can be inspected for recovery without being reactivated.

Recovery acquires the SAME kernel lock, verifies the recorded owner and inode
protocol, verifies the manifest, and reads provider state via the existing engine
in preview mode. Active owners, replaced lock files, legacy slots without the
protocol or externally changed ledger state are refused. Authorization is checked
again after reads. A single transaction records a checksum-protected recovery
receipt and clears the orphan slot. Verified uncertain items may become
DONE_VERIFIED and release their resource claims; unresolved items remain
UNKNOWN_NEEDS_READBACK with claims retained. BLOCKED_SECURITY stays blocked.
There is no apply() call, automatic replay, approval resurrection or WORK_COMPLETE
claim. Repeating the same recovery returns the original receipt only after fresh
authorization. Transaction failure preserves slot, claims and states.

All workers must use the same configured local service ledger and lock inode;
independent local databases are independent coordination domains. Neither POSIX
locking nor these tests attest cross-host/network-filesystem safety. No lock
file may be unlinked/replaced while workers exist. Upgrades must drain old worker
versions; a legacy slot without protocol evidence still requires an independently
approved quiescent maintenance procedure, not a forced marker or alternate path.
The production identity handoff, topology and recovery canary remain release gates.

### Complete-checkout local verification at 52b0ee1

The previous partial-source QA gate has been replaced with a complete git
worktree of the pinned PR revision and actual Prefect 3.8.8, using the SAME
prefect==3.8.8 / fastapi<0.155 constraints already defined by the operator workflow.
Dependencies are isolated under the QA workspace; the original environment,
published service and production configuration are unchanged. Temporary Prefect
API/SQLite instances are local-only; real cloud API credentials are disabled.

At commit `52b0ee12d62390e0f9add073afe6fcbb70010f0e`, the full repository
suite passed: 1,694 tests on Python 3.12, including six new
actual-runtime integration cases. Scheduling, context, signature verification,
DraftStore, grant/audit transactions, binding and recovery are real. Only the
upstream issuer handoff and TrainingPeaks provider are synthetic. Tests exercise
flow/task origin, standalone-task refusal, control lifecycle, replay of an old
invocation assertion and recovery without approval resurrection. This is NOT an
attestation of the existing production issuer, VPC bridge or deployed worker.

Complete testing also exposed inherited test defects (invalid literal preventing
collection, moved host-module path, frozen tool count and note mocks missing
coach/inventory preflight). These are corrected at their actual test contracts;
production plan/owner guards are not relaxed and no alias module or skipped test
is introduced. A real shared redaction defect was corrected: physical/escaped
line boundaries are normalized before credential-line redaction, including
quoted fields and spaced values. The existing admin receipt and operator output
both use that same function; endpoints and source/target policy stay unchanged.

Repository checks `ruff check src/` and `mypy src/` now pass (56 source files).
The parent commit had 53 Ruff findings and 43 mypy errors, independently reproduced
in a clean worktree. Repairs reuse the engine's existing Adapter protocol, narrow
validated identities and provider shapes, distinguish APIResponse/httpx transports,
and declare actual heterogeneous result types. Type casts only describe values
already checked by runtime guards; none replace validation or authorize an action.
Unknown plan objects/listing readbacks now return errors rather than reaching a
mutation/retry. Exception names follow the Error convention with import-compatible
aliases. Other lint repairs preserve tool schemas, endpoints and allowlists.
No type/lint suppressions, dependency changes or workflow edits were added.

The complete suite includes three additional regressions for unknown plan/listing
payloads, plus signed Prefect runtime and shared-redaction cases. Full local tests
and static checks do not imply a green GitHub Actions run: status/check runs must
be observed separately on the published commit. The stacked PR base is unchanged;
workflow trigger filters must not be bypassed to manufacture CI evidence.

### Debt and release gates

Owner below means the Operator component maintainer, not the coach/user.
No feature is WORK_COMPLETE while an applicable gate remains open.

| Classification | Item and reason | Target / removal condition | Verification |
| --- | --- | --- | --- |
| STRUCTURAL_REFACTOR — addressed | Divergent flow/Approval selectors and duplicate preview validators could drift | Shared selector and preview validators now used at both boundaries | Same-resource chain, corrupt records, existing regressions |
| STRUCTURAL_REFACTOR — addressed | Execution checks could create a binding using execute-only permission; grant checks did not inspect the exact persisted approval/binding | Use the common inspector without mutation; inspect approval/binding plus current grants/revocations/audit in one authority transaction. Reservation remains a distinct control permission | Four reproduced failures fixed; execute-only and corrupt-binding refusal, real SQLite exclusion, read-only revoked recovery |
| STRUCTURAL_REFACTOR — addressed | Explicit readback denials could become transient/uncertain states, including at orphan recovery and transport boundaries | Preserve the security category from local/native HTTP readers through the existing private bridge and common engine. Persist new recovery denials and retain uncertain claims; no automatic retry | Negative cases on prior receipts/postflight, private loopback transport, real Prefect recovery and restored-reader refusal |
| STRUCTURAL_REFACTOR — addressed | Draft/ChangeSet cycle checks and scheduling implemented the same graph contract three times; valid maximum-depth changesets could overflow Python recursion | One non-recursive dependency contract using the standard library, preserving stable ready batches and immutable input identity. Keep existing 500/1,000 item limits | Maximum chains/cycles, malformed shape errors before I/O, stable execution order and exact prior request/manifest hashes |
| STRUCTURAL_REFACTOR — addressed in one-ledger domain | Replaying request identity was not worker ownership | Invocation-owned persistent execution slot | Concurrent connections, resumed execution, dead process |
| SOURCE/TEST COMPLETE — runtime blocker | Concrete signed identity, scoped grants, revocation and audit implemented; trust/assertion handoff not configured live | Owner: Operator maintainer. Connect the existing issuer/launcher to invocation-bound assertions and pinned public trust before enabling control operations; retain default deny | Real signature/algorithm/issuer/audience/time/run binding tests, current grants, admin refusal, revocation, atomic control, audit; actual local Prefect coverage passed; production issuer/launcher and upstream revocation canary still pending |
| SOURCE/TEST COMPLETE — runtime blocker | Authorized local orphan recovery now uses kernel exclusion and preview readback in the same flow | Owner: Operator maintainer. Review/drain legacy workers and test on the canonical local runtime before release; no auto-takeover or legacy-marker workaround | Real child-process death, active owner refusal, inode mismatch, denial preservation, uncertain claims, rollback, idempotent receipt and revoked-approval recovery |
| MISSING — release blocker | One-ledger topology is not deployment-attested | Enforce a single canonical service ledger for all workers before live execution; no arbitrary per-request ledger paths | Real-runtime multi-worker canary and readback |
| STRUCTURAL_REFACTOR — addressed in source | Classic adapter constructed FIELD_VALIDATION_ONLY manifest to reuse validation | Pure field validator is now shared with the existing publisher; synthetic manifest removed | Identical acceptance/error parity and input immutability; publisher/adapter regressions |
| STRUCTURAL_REFACTOR — source/test complete, runtime gate pending | SKIPPED_DEPENDENCY legacy branch in normal execution | Branch removed in favor of atomic version 1 migration and full event backup. Owner: Operator maintainer. Inventory/rehearse the actual ledger snapshot and rollback before release; no mixed worker versions | Concurrent/idempotent migration, rollback, manifest drift, preserved claims/denials and dependent execution |
| RESOLVED — local QA | Partial-source snapshot and missing Prefect | Replaced by pinned complete worktree, actual Prefect runtime and full suite; production/CI attestations remain separate | 1,694 passed; local API/SQLite, signed invocation and orphan-recovery cases |
| RESOLVED — local static QA | Parent lint/type findings | Corrected contracts and local lint defects without weakening runtime checks or adding suppressions | Ruff src/ PASS; mypy src/ PASS, 56 files; full suite PASS |
| EXISTING_DEBT — before universal release | Plan-specific legacy helpers remain in plans.py, strength.py, beginner_strength_plan.py and native_note_library.py; their hardcoded pilot scopes are safety constraints, not universal interfaces | Owner: Operator maintainer. Keep isolated and unavailable to universal publication. Replace their callers with common typed capabilities only after semantic parity, scope review and an authorized capability canary; remove retired helpers/callers in the same review. Do not generalize by stripping IDs or allowlists | Inventory remaining callers; negative owner/scope and parity tests, then reviewed migration/removal; no new per-plan helpers introduced here |

Existing staging VPC allowlists and capability guards remain in place. Their
replacement requires request-scoped authorization review, negative scope tests
and authorized canaries; no policy removal or widening is part of this change.
Workflow edits and plan_mutation_gates changes previously denied remain excluded.
The proven publisher keeps its existing endpoints and scope gates; field validation
and local exclusion are shared components. No claim of live readiness.


### Follow-up: permission checks cannot reserve execution

Classification: STRUCTURAL_REFACTOR, with no temporary compatibility bypass.
Review of the common execution guard found that it called bind_execution after
checking execute_change. Thus an approved preview with an execute-only grant
could create its own execution reservation, bypassing the distinct bind permission.
The host authority also previously checked grants against preview/revision/scope
without itself checking the exact existing approval and execution binding.
Four negative cases reproduce these defects on 52b0ee1 before the fix.

DraftStore.inspect_execution_binding is now the single inspector reused by the
guard and concrete authority. It verifies the exact approval payload, binding and
manifest; active consent is required by default. Only the explicitly identified
read-only recovery action permits inspecting revoked consent, and recovery still
needs a current grant. Neither check creates/refreshes a binding or resurrects
consent. The serialized flow input exposes no allow_revoked switch.

HostReviewAuthority performs this inspection inside the same BEGIN IMMEDIATE as
current grants, token/principal/grant revocations and audit. Missing/corrupt binding,
missing/incorrect approval SHA and withdrawn consent deny execution. A concurrent
revocation cannot interleave between binding inspection and the grant decision.
A decision already completed before revocation is an in-flight decision, not a
promise to cancel a provider request already sent. Existing per-item checks remain.

The sole reservation route remains the existing independently authorized
bind_execution control operation. Publisher activation, adapter capabilities,
endpoints and worker protocol are unchanged. No provider writes, deployment or
production ledger migration were performed.

Verification of this follow-up is recorded separately from the full-suite result
above: 152 relevant tests passed across authorization, preview_approval,
worker_recovery and dynamic_request_store (15 new cases; four failed before the
fix). Cases include execute-only privilege refusal, exact/absent/corrupt bindings,
recovery after consent revocation without reactivation, and real concurrent SQLite
connections proving exclusion and subsequent revocation enforcement. An additional 53 tests passed
(3 warnings) across actual Prefect runtime, unified flow, changeset engine, worker
coordination and isolated flow contracts. Total for this follow-up: 205 relevant
tests, including real local Prefect/SQLite and synthetic issuer/provider boundaries.
Ruff src/ and changed-file F checks, mypy src/ (56 files), and diff checks pass.
The unchanged parts of the prior 1,694-test suite were not rerun. Local pytest
evidence must not be labelled GitHub Actions CI.


### Follow-up: preserve explicit denials through readback and recovery

Classification: STRUCTURAL_REFACTOR, reusing the existing read gateway, bridge,
engine and ledger; no temporary workaround or new production infrastructure.
Before this correction, generic exception handling could turn SecurityDenied
while rechecking DONE_VERIFIED/RUNNING/UNKNOWN_NEEDS_READBACK into an uncertain
read failure. Postwrite readback could similarly swallow the denial, and orphan
recovery could persist UNKNOWN_NEEDS_READBACK instead of the newly observed
security stop. Separately, the local reader treated final provider permission
errors as ordinary read failures and the existing bridge converted SecurityDenied
to HTTP 424, losing its category across the private transport.

The shared provider-access classifier now preserves final AUTH_EXPIRED,
AUTH_INVALID, FORBIDDEN_ENDPOINT and PREMIUM_REQUIRED responses from TPClient,
and native HTTP 401/403, as bounded SecurityDenied without provider diagnostics.
Plan, workout, note and library reads share the same checked GET helper. Native
Strength authentication failure also stops as SecurityDenied. Existing endpoints,
client token-refresh behavior, allowlists and transient-error handling are unchanged.
The existing private read handler returns a bounded 403 for provider SecurityDenied;
its existing remote reader already preserves 401/403 as SecurityDenied. Temporary
503 and generic 424 retain their previous categories. No fallback is attempted.

The engine uses one terminal-denial policy for initial/readback/reconciliation
security failures. Normal previews report BLOCKED_SECURITY without mutating the
ledger; execution persists it. Orphan recovery persists a newly observed denial
atomically with its existing receipt/slot transaction, even for an originally
verified or pending event. Existing denials retain their evidence. Uncertain
claims stay held. A restored reader or repeated recovery cannot clear a persisted
denial, claim completion or trigger another provider write. No security tombstone
is removed by this change.

Verification on this follow-up: 248 distinct relevant tests passed, including
39 new cases. The core/authorization/approval/coordination/local-reader group
passed 177 tests in 1.72 s; all 41 private/unified bridge cases passed within a
70-test run (29 overlapping reader cases are not counted twice). Actual Prefect
runtime, unified flow and isolated flow contracts passed 30 tests in 47.99 s
(3 warnings), including a new signed-authority recovery case proving durable
BLOCKED_SECURITY, retained claim and idempotent receipt after the reader recovers.
Synthetic provider/issuer and loopback HTTP only; no TrainingPeaks credentials,
cloud Prefect API or deployment. 27 engine/local-reader negative cases reproduced
the defect on the preceding source. Ruff src/ and changed-file F, mypy src/
(56 files), Python 3.10 syntax and diff checks pass. The full 1,694-test baseline
remains attributed only to 52b0ee1; unrelated tests were not rerun for this segment.
GitHub Actions CI and production issuer/topology/capability canaries remain
separate release gates. No merge, deploy or universal publisher enablement.


### Follow-up: one non-recursive dependency contract

Classification: STRUCTURAL_REFACTOR. Draft preparation, ChangeSet validation
and engine scheduling now reuse dependency_order in the existing operation
contracts module. It uses Python's standard-library TopologicalSorter with
explicit missing-node rejection and input ordering within each ready batch.
No package, service, job, manifest format, recursion-limit override or batch
splitting mechanism is introduced. Existing limits remain 500 items for drafts
and 1,000 for direct ChangeSets; this change does not harmonize or increase them.

A valid reversed chain of 1,000 existing resources previously caused
RecursionError during manifest validation; a cycle of that depth could fail the
same way instead of returning DEPENDENCY_CYCLE. Lists/dicts in depends_on or kind
could also raise TypeError before the declared shape/domain error. Six negative
cases reproduced these failures on the preceding source. Type/shape checks now
precede hashed membership, and the common graph contract returns the existing
DEPENDENCY_MISSING / DEPENDENCY_CYCLE codes in the caller's existing exception
class. Invalid graphs stop before worker acquisition, ledger registration,
resource claims or provider reads/writes.

The stored draft and compiled preview keep their input order and serialization;
only runtime execution follows dependency batches. A fixed regression records
request_id, semantic_sha256 and manifest SHA captured from 0708daf and verifies
exact equality after consolidation, plus input immutability. Maximum-depth
preview executes 1,000 synthetic reads without recursion or provider writes.
Existing same-resource direct-dependency requirements remain unchanged.

The new import path exposed type ambiguities in adjacent trust contracts.
Existing missing-preview rejection now uses an explicit narrowing branch;
review dispatch declares its dictionary result; run_control separates successful
return/audit from caught failure/audit while retaining transaction/savepoint
semantics. JWT verification explicitly checks the already-pinned RSA/Ed25519
key type at its algorithm branch. No algorithms, keys, grants or permissions
are added. Existing rollback/audit tests now also assert the denied audit outcome.
No casts, suppressions or workflow changes were introduced for these checks.

Verification: 245 distinct relevant cases passed, including 16 new cases.
Core/DraftStore/approval/authorization/worker/recovery/migration suites: 215 PASS.
Actual Prefect runtime, unified flow and isolated contracts: 30 PASS (3 warnings);
after the final authority type/control cleanup, the seven actual-runtime cases
were revalidated (7 PASS, 2 warnings), not counted twice. Ruff src/, changed-file
F checks, mypy src/ --no-incremental (56 files), Python 3.10 syntax and diff
checks pass. Provider/issuer remain synthetic. The full 1,694-test baseline is
still attributed only to 52b0ee1; unrelated suites were not repeated. No GitHub
Actions success, live canary, deployment or publisher activation is inferred.
