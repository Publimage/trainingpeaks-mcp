# PR19: reconciliation of the separate AI review

Reviewed base: `3874fd5d7c9bb312858102addbac256f26a92eb5`, 2026-10-28.
This is author remediation evidence for another independent review, **not
operational release approval**. No merge, deployment, app Refresh or TrainingPeaks
write was performed. Synthetic keys/providers exist only in disposable tests.

## Findings and exact boundaries

| Finding | Classification | Code evidence and disposition |
| --- | --- | --- |
| A-01 | **BUG CONFERMATO — corrected** | `src/tp_mcp/private_bridge.py:294` previously accepted an allowlisted IP without authenticating its peer. Both methods now require TLS client authentication and a pinned certificate/source policy before parsing bodies, provider reads or persistence; result sinks also require a writer role (`:367`). `src/tp_mcp/bridge_tls.py:42` uses standard TLS verification and existing protected-file readers; `:57` pins the authenticated certificate. Shared read clients verify the server, disable redirects/proxies and require host mTLS configuration. This authenticates services, not the human approver. |
| A-03 | **BUG CONFERMATO — recovery gap corrected within the delivered-assertion boundary** | `scripts/ironman_jobs/ironman_prefect_dispatch.py:155` reconciles the same held flow under the shared producer lock (`:63`, `:108`). `scripts/ironman_jobs/ironman_authorization.py:618` verifies an already delivered assertion, exact issuer/subject, flow, command, expiry and current revocations using the existing authority transaction. No new assertion, approval or flow is issued. Undelivered, corrupt, stale, revoked or mismatched evidence leaves the run held. The remote authoritative reconciliation port remains a production gate. |
| A-02a | **BUG CONFERMATO — missing/empty ledger corrected** | `scripts/ironman_jobs/ironman_unified_prefect_flow.py:161` and `:184` open execution/recovery ledgers existing-only. `ironman_local_state.py:59` refuses absent/zero-length history and opens SQLite with `mode=rw`; `ironman_unified_changeset_engine.py:153` requires the existing core schema before migration. Lost execution history can no longer be silently initialized as a fresh ledger by these paths. |
| A-02b | **GATE DI PRODUZIONE** | A coherent older backup of all local state cannot prove its own freshness. Existing `tests/test_ironman_authorization.py:623` demonstrates why pre-revocation state must not be restored as current authority. Fence producers/workers, preserve current tombstones/claims/receipts, obtain fresh upstream revocations and reconcile uncertain provider outcomes before readmission. No local hash or test snapshot is claimed to prevent complete historical rollback. |
| A-04 | **GIÀ RISOLTO in the integrated code; live identity remains gated** | `ironman_authorization.py:29`, `:548` bind the grant to issuer, subject, request, preview, revision, scope and original manifest; `ironman_operation_contracts.py:39` checks exact targets; `ironman_dynamic_request_store.py:596` checks the stored approval/binding. Existing negative tests: `test_ironman_authorization.py:125`; `test_ironman_preview_approval.py:121`, `:127`, `:153`, `:163`. An approval digest alone is not authority. These suites were inspected, not unnecessarily replayed. |
| B-01 | **FALSO POSITIVO on integrated PR19** | `prefect/ironman-unified-changeset-v1.yaml:19` exposes only `mode: preview`; privileged PR18 parameters are absent. Launcher and worker enforce domain-only parameters. YAML was not changed or restored. |
| B-02 | **GATE DI PRODUZIONE** | Real human IdP/delegation, fresh authoritative revocations, existing host PKI, protected worker configuration and administrative runtime access are not supplied by laboratory identities. The software ports do not attest their installation. |
| B-03 | **GATE DI PRODUZIONE / CI** | Official checks must be inspected on the final exact SHA. Existing trigger filters exclude the PR19 base; local QA is not GitHub CI. No protected workflow, trusted branch, artificial event or denied operation was changed to obtain green checks. |

Paths without a directory above are under `scripts/ironman_jobs/` or `tests/`
as indicated. The pre-fix differential reproduction accepted unauthenticated
`GET /health` from an allowed loopback IP (HTTP 200); the patched handler rejects
that same request (HTTP 403). No provider was contacted.

## Focused verification

Results are separate, overlapping scopes, not a summed full-suite count:

* First focused bridge/dispatch/ledger regression pass: **106 PASS, 37.12 s**.
* Updated peer-authentication, held-flow recovery, ledger-loss and dispatch scope:
  **24 PASS, 28.81 s**. The native Prefect hold test checks a lost delivery ACK,
  unsafe evidence rejection and concurrent reconciliation: one confirmed release,
  one original assertion delivery, the same flow ID and no provider execution.
* Final ledger fixtures: **5 PASS, 0.27 s**, including real stored approval and
  signed admission through the flow before missing/truncated-ledger rejection.
* Existing native MCP/Prefect positive lifecycle selected after changing the
  ledger-opening contract: **1 PASS, 20.76 s**. Initial ledger creation is explicit
  trusted host provisioning, separate from request execution/recovery.
* Additional legacy IP-only config rejection: **1 PASS, 0.34 s**.
* Source Ruff, new test/helper Ruff, mypy (**59 source files**), affected compile
  and whitespace checks pass. Previously completed long-running HTTP/worker and
  twelve-run lab suites were not replayed.

Local logs/JUnit: `../pr19-review-fixes.*`, `../pr19-review-targeted.*`,
`../pr19-review-ledger-final.*`, `../pr19-review-positive-regression.*`,
`../pr19-review-config-fence.xml`, `../pr19-review-types.log` in the execution
workspace's `work/` directory. They are local QA artifacts, not CI attestations.

## Required installation and review gates

1. **Coordinate TLS migration on the existing bridge and every real client**,
   including Radar/admin/monitoring clients outside these shared Python clients.
   Server `tls` has exact keys `ca_file`, `cert_file`, `key_file`, `peers`;
   paths must be absolute, protected host files. `peers` maps a lowercase SHA256
   DER leaf-certificate fingerprint to `sources` and boolean `result_writer`.
   Clients set protected-host `IRONMAN_PRIVATE_BRIDGE_TLS_CONFIG` to JSON with
   the three file paths; use existing approved PKI with server SANs matching the
   private HTTPS address. No PKI or credentials are provisioned by this change.
   Missing TLS fails closed; there is no plaintext compatibility bypass. This
   candidate must not be deployed piecemeal over the existing HTTP clients.
2. Install `delivered_invocation_reconciler` **at authoritative worker-side
   storage**, not on a stale producer token copy. Connect its host-only port to
   the launcher with a single protected `coordination_path` shared by all MCP
   producer processes on that host. This reuses POSIX exclusion, not distributed
   or NFS locking. All allocators/reconcilers and maintenance must respect the
   same fence; privileged API overrides are outside its guarantee. Different
   IdP/delegation namespaces need an attested mapping, never an email heuristic.
   The worker still rechecks actual business grants and approval before IO.
3. Keep missing assertions held: neither timeout nor receipt loss authorizes
   minting a replacement. Wire real delivery/reconciliation and upstream
   revocations before claiming autonomous production recovery. Current code
   supports recovery of durable, still-current delivered evidence only.
4. Initialize a ledger once during trusted initial host provisioning. After loss,
   do not initialize it again to clear the fence. Verify backups, current authority,
   claims, receipts and provider state under quiescence; a code rollback must retain
   current data and revocations. An actual host restore exercise is still required.
5. Independent review of the exact candidate and its PR18 dependency, official CI,
   real IdP/feed, runtime management and rollback evidence remain independent
   release gates. The requested reviewer is already assigned; no repeated owner
   assignment, Actions enablement or app-auth inspection is needed.

No temporary plaintext path, request-specific job, new service or infrastructure
was added. Legacy read-only diagnostic scripts were not repurposed or changed;
their transport compatibility is part of the coordinated rollout gate. The
previously denied self-test, mutation-gates file and workflow are untouched.

## 2026-10-30 — corrections from the Linux review of 396ce1c

The separate technical review of the integrated candidate ran the entire suite:
1905 passed and 7 failed. This follow-up addresses its six finding classes without
altering production trust, workflow triggers or deployment parameters:

- R1: the common pinned JWT parser requires a textual `typ` before set membership.
  Both worker and OAuth profiles reject malformed types as authentication errors.
  Real ASGI regressions alter unsigned headers to list/dict values and require
  HTTP 401 with no operator admission; there is no broad exception suppression.
- R2: trusted initial ledger provisioning belongs only to scenarios that execute.
  Control-only/capability-denial fixtures no longer provision it in advance. The
  six existing assertions that controls/denials do not create the execution ledger
  remain intact. Execution and orphan scenarios still provision explicitly.
- R3: the deployment test requires exactly `{"mode": "preview"}`. No privileged
  transport/path parameter is restored. The YAML and worker trust gates are unchanged.
- R4: the admin receipt projection has an explicit `dict[str, Any]` annotation;
  full source mypy now passes, without disabling a check.
- R5: uv.lock now matches project 3.2.0 and its already declared runtime/dev extras,
  including Prefect 3.8.8, FastAPI, Pillow and fitdecode. Resolution preserves
  existing pins where compatible; this is not a blanket dependency upgrade.
- R6: keyring availability uses the backend's documented positive-priority API,
  including its unavailable-priority failure, rather than a class-name heuristic.
  Tests use real fail/null backends; encrypted fallback remains intact. No real
  credential is read/written to verify backend capability.

Verification includes a new isolated `uv sync --locked --extra dev` installation,
lock consistency and installed dependency checks. The locked environment uses
MCP 2.0.0 / cryptography 46.0.5 / keyring 25.7.0 / Prefect 3.8.8; the fresh-install
review environment uses MCP 2.3.0 / cryptography 50.0.2 with the same keyring/Prefect.
Focused locked tests: 139 PASS, 2 deselected. Fresh-install affected authentication,
HTTP, keyring and all seven formerly failing cases: 66 PASS, 21 deselected, 53.99 s.
These are overlapping scopes, not a full-suite total. Ruff source/new tests and
full source mypy pass in both dependency environments; the real SDK 1.26 client
also passes against the locked server. The full locked regression is warranted
because the previously stale lock records different SDK/transitive versions.

The operational release remains gated by independent review, official exact-head
CI, real human identity/delegation/revocations, authenticated runtime management,
coordinated all-client mTLS migration, authoritative held-run reconciliation and
verified state-preserving backup/rollback. No new service, request-specific job,
manifest, permissive fallback or temporary workaround is introduced. No merge,
deploy, app Refresh or TrainingPeaks write is performed by this follow-up.

Final locked full-suite result: **1923 PASS, 0 failures/errors/skips, 378.34 s**.
All seven previously failing cases pass with their safety assertions preserved.
One existing Prefect logging-context warning remains; no warning/error is suppressed.
Local artifacts: `work/pr19-review-evidence/fixes-full.*` (actual workspace path
`/workspace/pr19-review-evidence/`), `fixes-focused.*`, `fixes-fresh-regression.*`,
`fixes-legacy.log` and `fixes-locked-install.log`. These are local QA, not GitHub CI
or an independent approval. The original 396ce1c review remains historical evidence
of the pre-correction candidate; this result supersedes its local failing checks.
