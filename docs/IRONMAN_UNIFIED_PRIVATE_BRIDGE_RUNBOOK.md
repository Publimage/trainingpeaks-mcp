# IRONMAN unified preview — private VPC staging runbook (NOT DEPLOYED)

Purpose: connect the **existing** Prefect staging worker to the **existing** private TrainingPeaks bridge, without moving TP cookies/tokens and without opening another web service. One `IRONMAN_CHANGESET_V1` can preview workout, note, PDF metadata, native Strength and Library changes across authorized plans. No new job per plan, workout or PDF.

## Source and trust boundary

- Source of truth: canonical Drive `11_AGENT_ORCHESTRATION_ROADMAP`, `00B_IRONMAN_EMERGENCY_ACCESS_AND_RECOVERY`, `00C_IRONMAN_PROVEN_PATHS_REGISTRY`.
- Endpoint in existing `tp_mcp.private_bridge`: `POST /v1/unified-resource-read`, bound to the currently configured private VPC address, not public interfaces.
- Caller allowlist uses the existing `allowed_sources` IP control. Do not expand it or alter the existing Radar or CSS policies unless independently approved.
- New opt-in key `allowed_unified_reads` defaults to `[]` (deny all). Each entry must list the exact Training Plan/Workout Library container, resource kinds, and nonempty `resource_ids` allowlist. A resource ID outside that list is denied before the provider read. Older entries without `resource_ids` are invalid and must not be silently broadened.
- Only exact `{"spec":{"kind": "...", "target":{...}}}` payloads. Every target is bound to owner ID `2116886`, typed container ID, resource ID and provider.
- TP authentication and native data reads remain in the existing TrainingPeaks host process. The read-only VPC response is strictly bounded and strips credential-like keys and signed URLs.
- The Prefect client disallows HTTP redirects, network proxies, arbitrary URL selection and writer methods. An out-of-scope response is rejected.
- The new Prefect flow rejects `mode=publish` before opening any provider connection. A new manifest does not authorize writes.

## Staging preparation (requires normal authorized operator/deployment approval)

1. Review PR 18 and its offline tests. Do not merge or deploy on a failed/unknown CI result.
2. Inspect the real server-local `private_bridge.json`, preserve Radar/CSS entries and add ONLY the exact approved plan/library scopes to `allowed_unified_reads`. Sample **schema only**, not a ready-made approval:

```json
"allowed_unified_reads": [
  {
    "provider": "trainingpeaks",
    "owner_id": 2116886,
    "container_kind": "training_plan",
    "container_id": 123456,
    "kinds": ["plan.workout.patch", "plan.note.patch"],
    "resource_ids": [111111, 222222]
  }
]
```

3. Validate existing source IP allowlist and private bind; stage a controlled reload of the existing bridge after revision review. No new public listener or credential forwarding.
4. Ensure the separate Prefect worker has a copy of the reviewed code and an existing private directory for `/var/lib/ironman-prefect/unified-changesets/ledger.sqlite3`, owned by its non-root service account. No changes to TP-host credential permissions.
5. Deploy only `prefect/ironman-unified-changeset-v1.yaml` (`mode=preview`, `read_transport=private_bridge`, no schedule). It reuses the existing work pool. Do not use the old CSS deployment for generic requests.
6. Run a **single synthetic/approved read-only** changeset on a disposable Training Plan and verify every returned object, SHA, expected pre-image, owner and counts. Check Radar and CSS still return their original read-only results.
7. Verify no provider mutations, HTTP redirects, credential fields or unexpected file URLs. Verify denial of a different plan and a different source IP, and state recovery for a duplicate request ID.
8. Record provider readback and logs in the canonical KB only after successful staging evidence.

## Next gated capability: generic writes

A separately reviewed release can wire the original Proven Path adapters ONCE for each resource kind to the same changeset runner. Required: cross-host lock, durable idempotency, exact review/approval scope, full before/after provider readback and disposable-plan fault injection. Never run previously denied T1500/PDF operations as an alternative route around security controls.

## Status

**Code and CI candidate in PR 18; not merged, not reloaded, not yet smoke-tested on staging, no real TP writes.** This contract is a controlled implementation checkpoint, not a deployment authorization.


## Scope of static resource_ids: staging only, not the future product boundary

The mandatory resource_ids in allowed_unified_reads are deliberately a *fixed, opt-in read-only STAGING canary* safety boundary. They are not a permanent list of workout IDs, athletes or plans allowed for all future ChatGPT requests. The final service must discover NEW, previously unseen accessible TrainingPeaks resources dynamically in response to each authorized current request without an administrator editing private_bridge.json or pushing a GitHub manifest for each batch.

To reach that state safely, design a separate reviewed **dynamic provider discovery and request-scoped authorization capability** within the existing authenticated TP MCP host/bridge, not a general API proxy. It must re-check account identity, coach–athlete association, permissions, target kind/IDs and request operation; accept only typed requests; issue bounded short-lived scopes; reject wrong plan/athlete, ambiguous targets and stale/replayed scopes; keep tokens/URLs and provider credentials on the TP host. Protect against cross-session/request substitution with durable request_id and provider readback.

Do NOT skip the current allowlist or reinterpret a security 403 as a generic transport error. Until dynamic security is independently reviewed/tested and deployed, PR18 only supports canary resources expressly allowlisted. Do not describe its read bridge as able to publish to any TrainingPeaks resource. This is an OPEN RELEASE GATE, not a configuration change to perform now.

## Management, identity and rollback acceptance — 2026-10-27

This is the preparation/checklist for the existing runtimes, **not an executed
deployment or a new Proven Path**. Current Codex runtime observations show no
bound runtime credentials/identities, no VPN and no private TCP grants. The DO
connector supplies inventory, not a shell. The Social forced-command deployment
channel is expressly excluded. No credential generation, new service or
per-request job is a substitute for authorized TP/Prefect service management.

Before changing either host, the authorized runtime maintainer must attest the
actual service account, working directory, executable revision, dependency set,
service manager, private bind, existing bridge policies and health checks. Record
paths/UID/modes and checksums, never secret values. Inventory the canonical
DraftStore and execution ledger together with active worker ownership/claims,
schema version and approval/grant/token/principal revocation history. SQLite and
POSIX flock require one supported local filesystem and worker topology; a local
lock is not evidence of a distributed lock across two hosts or NFS.

Use the existing private host trust/assertion inputs. They must reside below
trusted directories and be regular, bounded, private files. Reads reject FIFOs,
unsafe ancestors and changes during the read. A completed atomic file rotation
is accepted by a later read. These checks do not authenticate an approving human:
the existing issuer must provide pinned public trust and a signed assertion for
the **actual** Prefect flow invocation. Configure the private, host-owned
`IRONMAN_REVIEW_ASSERTION_DIRECTORY`, not the removed shared-file input. The
launcher uses `assertion_path_for_invocation(directory, actual_flow_run_id)` to
select the file: SHA256 of the canonical JSON string of that ID, plus `.jwt`.
The worker derives that same ID from trusted flow/task context; neither a path
nor an invocation ID is accepted from MCP/flow parameters. Install the signed
assertion atomically with private permissions before admitting that run. Separate
runs never overwrite each other's assertion. The existing issuer/launcher owns
expiry cleanup after terminal runs; recovery requires its own new signed origin.
No files, keys or directories are created by the verifier. Old
`IRONMAN_REVIEW_ASSERTION_FILE` configuration is rejected, including when both
variables are set. This is a change to an undeployed contract, not a dual-mode
compatibility workaround. Upstream revocations must reach the same authoritative store before
subsequent decisions; a JWT signature alone cannot establish current account
status. The existing host administration API now accepts a bounded atomic
`revoke_many` batch, with the same administrator signature, revocation checks and
audit transaction as `revoke`; neither method is exposed to MCP/flow callers.
Invalid/interrupted batches roll back completely. Re-delivery only adds durable
tombstones; it never clears an existing revocation. This primitive is not a feed
transport or proof of delivery freshness. No issuer/launcher or upstream delivery
has yet been attested live.

The MCP boundary must derive identity from its trusted authenticated transport,
never `athlete`, a caller-supplied principal/JWT, a stored approval hash or a
serialized callback. Its generic request dispatch must call the one existing
`ironman-unified-changeset-v1` flow. The present stdio/fixed-job runner supplies no
verified human identity handoff; do not add a permissive facade or expose an
admin grant/revocation tool to compensate. `prepare`/preview persistence does not
itself confer request authorization. Dynamic VPC discovery/authorization and
each writer remain independent gates even after lifecycle wiring.

The controlled upgrade/rollback procedure must be rehearsed on private copies
before applying it to live state:

1. Stop admission and drain the affected operator workers using the existing
   service manager. Preserve uncertain/in-flight claims. Do not terminate or
   reconfigure unrelated Radar, CSS or Social services.
2. Take consistent SQLite online backups, or checkpoint/copy only with all
   connections closed. Copying a live main DB while ignoring WAL is insufficient.
   Preserve both stores' matching history and private permissions. Verify
   integrity and recorded counts/hashes on the isolated copies.
3. Verify the exact approved release/dependencies and schema compatibility on
   those copies. Reopen after process restart, confirm the same request/preview,
   approval, tombstones, grants and execution binding; duplicates must reuse
   receipts, revoked requests must remain denied, uncertain writes must require
   independent readback before any retry.
4. Roll back **code/configuration only** if compatible with current schema and
   history. Never restore a pre-revocation or pre-write DB as an ordinary code
   rollback: it can resurrect authority or lose an idempotency receipt. If old
   code cannot safely read current state, leave operator admission stopped and
   perform reviewed forward recovery. Backup restoration is disaster recovery
   requiring reconciliation of later revocations/provider outcomes first.
5. Resume a single controlled worker, attest canonical paths/UID/permissions and
   read-only service health, then verify independent existing-service checks.
   Recovery of an abandoned worker is the existing authorized read-only flow
   mode, not deleting a lock or manufacturing a new worker owner.

Local crash/reopen/revocation/migration tests support these contracts; they do
not prove production filesystem topology, actual backups or rollback. Acceptance
evidence must record the real host/service, exact code SHA, snapshot integrity,
before/after health and preserved authority/receipts. No provider writer may be
enabled until all applicable CI/review, identity, topology and per-capability
disposable-canary gates pass.

## Existing access paths and missing handoff — 2026-10-27

Sources: canonical 00B Emergency, 00C Proven Paths, 11 Orchestration, 20 Connector
Runbook and 21 State marker `DO_READONLY_20261027_V1`. Historical console evidence
identifies the following paths; it is not current service-configuration inspection.

| Boundary | Existing path | Limit |
| --- | --- | --- |
| TP maintenance | Owner's DO console / passphrase-protected Mac SSH identity `~/.ssh/ironman_tp_mcp`; public key IRONMAN-TP-MCP, DO ID 59993332 | No private maintenance identity is bound in Codex; a public DO key is insufficient |
| TP process | `ironman`; `/home/ironman/trainingpeaks-mcp`, `/home/ironman/tp-mcp-venv`; service `ironman-trainingpeaks-tunnel` | Fixed pinned jobs/reload are not unrestricted administration; do not repeat bootstrap |
| Prefect maintenance | Owner's console; `ironmanprefect`; `ironman-prefect-server` and `ironman-prefect-worker`; API loopback `127.0.0.1:4200` | VPC/SSH reachability and old process receipts do not grant current access |
| Prefect execution | Pool `ironman-prefect-staging-process`; CSS source `/opt/ironman-prefect/swim-audit-src`; state `/var/lib/ironman-prefect` | CSS deployment is not the universal deployment or a general launcher |
| Admin results | `/v1/admin-result` sink plus `prefect_admin_result_read_20261016` | Receipt ingestion/retrieval, not a command or signing endpoint |
| Social receiver | Separate restricted maintenance channel on Prefect host | Explicitly excludes TP/Prefect |

A new live read using the registered result reader at trusted SHA `4b45d9a`
returned DONE/exit0 and `bootstrap-status-20261016-001`. This is an old status
receipt from 2026-10-16T20:44:38Z–20:44:43Z: state FAILED; then server/worker
active, Prefect health true, bridge health URLError. Later verified CSS bridge
flows supersede that historical network failure. Neither current failure nor a
usable administrative command channel follows from this receipt. Nothing was
restarted or retried.

The missing access is a protected maintenance connection to these existing hosts,
made available to this repository's managed Codex environment by the owner.
Reuse/verify the existing identity, account and host fingerprints; no replacement
key, password reset, Social receiver expansion or secret in chat/Drive/Git.
Credential/identity binding belongs in protected Codex environment configuration;
matching account authorization and bounded network access belong on the existing
hosts/environment policy. Current observations report no such bindings. DO's
connector supplies droplet operations, not an authenticated terminal. This is
access provisioning, not another application installation.

No inspected canonical path identifies a production issuer of human approval
assertions. A tunnel key authenticates the tunnel, a TP cookie the provider
account, SSH maintenance access; none proves who approved an MCP request. The
stdio server consumes no trusted human delegation. The workspace/tunnel identity
owner must attest the identity mechanism, issuer/audience/public keys and how
authenticated request identity reaches the launcher. Do not invent keys or accept
a caller principal/JWT. If unavailable, this is an integration design gate, not
a missing TP password.

After that boundary is attested, the existing Prefect worker's protected host
environment supplies `IRONMAN_REVIEW_TRUST_CONFIG`,
`IRONMAN_REVIEW_ASSERTION_DIRECTORY`, `IRONMAN_OPERATION_DRAFT_STORE` and
`IRONMAN_OPERATION_EXECUTION_LEDGER`. Attest actual private paths/UIDs before
installation: no universal DraftStore path has been inventoried live. The trusted
launcher installs each flow's assertion before admission. Revocation delivery
uses the existing admin API under a current signed administrator; freshness and
loss/reconnect must be verified. Source primitives do not prove this deployment.

## Backup rehearsal and restoration fence

New DO evidence: daily managed Prefect backups, no active DO policy attested on
TP. Historical Prefect backups also use `/opt/ironman-prefect/backup_prefect.py`
and `ironman-prefect-backup.service`/`.timer`. These metadata backups do not prove
coverage of the new authority store/ledger or the existing TP pilot DB
`/home/ironman/.local/state/ironman-operator/workflows_v1.sqlite3`. Inventory actual
paths and restore points first; do not enable paid options/create snapshots from
an inventory result alone.

Three new isolated rehearsal cases PASS on current modules, with synthetic data:

1. With admission quiescent across both copies, SQLite online backups preserve
   every SQL table/row, permissions and integrity. Reopened copies retain revoked
   consent, grant/token/principal tombstones, audit, preview/binding and completed
   execution receipt; restored authority denies. Two backups alone do not provide
   a cross-database atomic snapshot while admission remains active. Quiescence
   covers flow/control/admin writers, not just the provider worker. Any upstream
   revocations arriving during maintenance must be preserved and reconciled
   before readmission; no delivery queue is assumed to be installed.
2. A pre-revocation copy still authorizes its old grant while current state denies
   it. A historical local DB cannot discover later revocations. Code rollback
   must preserve current state; disaster restore stays fenced until reconciliation
   of subsequent authority changes/provider outcomes. No standalone historical
   DB anti-rollback guarantee is claimed.
3. An orphan RUNNING worker/uncertain claim survive copying, but the new inode
   causes recovery to refuse WORKER_QUIESCENCE_UNVERIFIABLE before provider I/O.
   Both records remain. Do not rewrite protocol identity/delete claims; real
   restoration requires separately reviewed fencing of the original topology.

Local rehearsal is not a live backup/restore. No restore routine, job, service or
temporary bypass was added. Actual backup coverage, restore fencing and upstream
revocation freshness remain release gates.
