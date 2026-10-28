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

## Worker reconstitution — source/lab verified, not deployed

`IRONMAN_OPERATOR_WORKER_CONFIG` selects one private process configuration:
deployment ID, entrypoint SHA256, existing DraftStore/ledger/trust/assertion paths,
read transport, revocation age limit and capability kinds. Existing environment
path variables must match. It cannot select a module/plugin or create an issuer.
The existing deployment YAML leaves these privileges to the host; requests carry
only mode, manifest and independently confirmed targets. Overrides are rejected.

The trusted launcher admits the MCP request, obtains the real Prefect flow ID,
then installs the private assertion with signed `run_id` and `command_sha256`
before releasing scheduling. Production delivery is not configured. Signature,
expiry and current revocation are checked before domain mutation/provider I/O.
Host authority `refresh_revocations(sequence)` may confirm a completed upstream
sync only; failed/partial sync must not refresh it. Tombstones remain monotonic.
The worker requires a fresh checkpoint and rechecks it for business decisions.

Trusted startup code can install reviewed adapters via `install_worker_adapters`
once. No request-selected loader or serialized callback exists; default writers
are empty and each kind still needs its own host gate. Results use bounded,
command/flow-bound receipts in the existing Prefect API. Inspect the returned
flow ID on failure/uncertainty; never resubmit blindly. The source ports are
tested with separate processes but do not attest live API access, issuer/feed,
dependencies, host state or rollout. No real listener/firewall/secret/service was
changed, and no new server, per-request job or operation manifest was created.

## Single controlled installation on the existing runtime — not executed

Use one maintenance session on the existing MCP and Prefect hosts after review
and exact-head CI pass. This procedure connects existing ports; it does not
create an issuer, service, work pool or per-request deployment. Missing evidence
at any step keeps that boundary closed. The source laboratory is not evidence
that these identities, routes or files are installed in production.

1. **Attest the trust contract before installation.** The identity owner identifies
   the actual authenticated MCP principal, issuer/audience, pinned public keys,
   approved administrative subject and upstream revocation source/sequence.
   Define the authenticated operation intent ID that remains stable across
   retransmission/reconnect/token renewal. Bind it to issuer, subject and exact
   command; never derive trust from tool arguments, a random per-attempt ID or
   an assistant-minted key. Missing real issuer/feed is a design gate, not a
   request to create credentials. Keep private keys/tokens out of Git, Drive and
   chat. `authorize_request` must perform current admission on every call,
   including historical receipt retrieval; `resolve_identity` uses that same
   request-scoped verified context, not an unverified principal object.
2. **Verify existing access and preserve state.** Use only the owner's authorized
   maintenance path to the existing hosts. Attest the actual Prefect deployment
   UUID, pool/entrypoint, protected API address and authenticated MCP-to-API route;
   historical loopback access or membership in the VPC is insufficient. API run
   metadata and artifacts are part of the trust boundary, not signed provider
   evidence: restrict who can mutate them. If no approved route/identity exists,
   stop that connection; do not expose the loopback listener publicly or reuse
   Social credentials. Drain/fence all flow/control/admin admission, inventory
   actual state files and open/uncertain runs, preserve current revocations and
   take coherent protected SQLite backups plus Prefect metadata backup using
   existing facilities. Retain run records/idempotency keys and assertion files
   for the full retry/reconciliation lifetime. Verify restore coverage/ownership
   and current services before applying any configuration.
3. **Connect the host ports once.** The existing trusted MCP startup installs
   `OperatorBindings` and `PrefectProcessLauncher` with the attested deployment,
   admission/identity resolver and issuer delivery port. Only mode, manifest and
   targets travel in flow parameters. The issuer port must durably and atomically
   deliver the assertion into the worker's protected assertion directory before
   acknowledging success, bound to the returned real run ID and command digest.
   No MCP signing key is required merely to verify incoming identity. Use the
   issuer's existing authorized delivery channel; its absence remains a gate.
   The launcher allocates a non-scheduled Pending run and only its persisted
   creation owner releases it. Retransmissions observe the same run. A partial
   delivery or producer crash may leave a held run: inspect that exact run and
   current authority/provider evidence under fenced maintenance; never generate
   a new intent, re-sign, release or cancel it as an automatic retry workaround.
4. **Connect the protected worker and feed.** Existing worker startup supplies
   private `IRONMAN_OPERATOR_WORKER_CONFIG`, matching environment paths, exact
   deployment/entrypoint SHA, validated installed dependencies and code bootstrap.
   No configuration comes from the request. The existing feed consumer delivers
   tombstones through `revoke_many`, then confirms a completed current upstream
   sync via `refresh_revocations(sequence)` under the real administrative
   assertion. A timer alone must not refresh freshness. Missing/failed/gapped
   synchronization keeps admission closed; verify restart/reconnect preserves
   tombstones and sequence. Choose the host age policy within 1–300 seconds.
   Keep writer installation and each capability independently disabled pending
   their review/provider gates; no universal publish flag is enabled here.
5. **Validate, then admit only the authorized scope.** Verify protected-file
   UID/modes, actual flow origin, current revocations, identity isolation, bound
   receipt transport, durable state and service health through the approved
   runtime path. Laboratory receipts are not substitutes. Any provider canary
   requires its separate disposable-resource/capability authorization. Before
   rollback, stop new admission and establish worker quiescence; preserve current
   stores, tombstones, claims, assertions and Prefect records. Revert code/config
   only to a compatible revision. A historical database restore remains fenced
   until subsequent revocations and provider outcomes are reconciled; never clear
   uncertainty or revive approval by restoring an old copy. The initial Pending
   hold is not an operator lock: privileged manual API transitions remain within
   the trusted maintenance boundary and cannot bypass these checks.

Release review tools: the official GitHub connector can read exact-SHA runs,
checks and submitted reviews. It cannot turn local QA into CI or independent
approval. The dedicated workflow excludes PR19's current base; its protected
filters are unchanged. DO's available connector has droplet metadata/lifecycle
operations but no authenticated process terminal. A browser skill being listed
does not supply an active browser-control tool; none was callable in this cycle.
No source change can attest an unconnected administrative session or upstream
human identity. The concrete identity design and first owner interface action
below supersede the earlier request to identify an unspecified maintainer.
Independent review, authorized CI coverage and actual runtime access remain
separate release gates.

## Human approver: private OAuth HTTP ingress — design, not installed

Checkpoint input: `IRONMAN_TUNNEL_STDIO_IDENTITY_LIMIT_20261027_V1`.
Official OpenAI tunnel architecture distinguishes the following boundaries:

| Evidence | Authenticates | Does not authorize |
| --- | --- | --- |
| Tunnel runtime API key | tunnel-client to OpenAI control plane | A particular human or changeset |
| ChatGPT membership / tunnel access | Use of the workspace's connector | A verified human principal at the stdio child |
| TP cookie / SSH identity | Provider account / host maintenance | Human MCP approval |
| MCP OAuth access token | IdP subject delegated through a registered client to this MCP resource | Exact preview, binding or provider write |
| Existing grants / signed invocation | Exact operation/revision/subject/run and current authority | Unrelated resources or capabilities |

Current source is `stdio_server() -> server.run(...)`; no HTTP Authorization
header is delivered to that stream. Tool arguments, JSON-RPC metadata, an email,
an API key or a static injected header cannot fill the gap. Current host/plugin
configuration was not inspected live. Official plugin search returned no exact
TrainingPeaks plugin record, although its connected tools exist; absence from
search is not proof of no app, no OAuth or access denial. No backend plugin ID
was guessed, and no OAuth settings were changed.

**Selected architecture:** ChatGPT's OAuth authorization-code + PKCE/S256 flow
with an existing compatible IdP; the SAME Secure MCP Tunnel and main binding;
Streamable HTTP into the SAME TP MCP application on loopback on `ironman-tp-mcp`;
existing operator bindings/launcher and the existing separate Prefect worker on
`ironman-prefect-staging`. Reuse the SDK HTTP session manager and registered
handlers, not a JSON-to-stdio wrapper that loses per-request transport identity.
No public MCP port, new droplet, authorization server, per-plan job or parallel
application service. Changing from the current stdio binding requires a reviewed
runtime change using existing process supervision; it is not performed here.
Local HTTP transport/discovery must meet the existing TLS/Host/Origin policy;
no plaintext-discovery override or disabled validation is enabled to make it work.

The HTTP resource must publish RFC 9728 protected-resource metadata and a 401
Bearer challenge. The IdP must support discovery, resource/audience binding,
PKCE S256 and a supported registration method (CIMD, DCR or predefined client).
Use the canonical resource and issuer from the actual tunneled discovery and
IdP configuration, never a guessed audience or loopback URL. Pin trust and human
subject/client mappings in host configuration. Per-request verified SDK identity
must populate BOTH `subject` and `claims.iss`; a shared ChatGPT `client_id` alone
cannot identify the session's human owner. Preserve request-scoped context into
the launcher. Keep legacy tool capabilities independently restricted; adding
HTTP must not implicitly authorize every existing write handler.

An existing workspace IdP is suitable only if it can issue access tokens for this
MCP resource. Connected Google Drive credentials, workspace SSO, an ID token or
a Google API access token do not establish that capability. No such provider is
attested yet. Sign in with ChatGPT is documented for participating integrations;
its availability for this private custom app is not established and is not the
default plan. No new identity tenant or synthetic production issuer is created.

**Independent software completed:** `OAuthHumanIdentityVerifier` reuses the
existing pinned-signature parser and issuer/audience/time/scope checks. Its opt-in
RFC 9068 access-token profile requires `typ=at+jwt`, configured human subjects
and OAuth clients; it does not require or fabricate `run_id`. It returns a
separate immutable `OAuthHumanIdentity`, not the worker's `Principal`, an approval
or a grant. Pinned RS256/EdDSA keys are supported; opaque tokens/other profiles
remain refused and need the real IdP's reviewed adapter if actually selected.
`OAuthMCPTokenVerifier` implements the installed official SDK verifier port,
preserving issuer/subject/client for session ownership. It requires a separate
async current-revocation policy, rechecks expiry after waiting for that policy
and returns no authenticated SDK token on denial/unavailability. Neither class
is registered with the live server. No HTTP listener, auth endpoint, identity,
credential, signing key, grant, issuer or feed consumer is installed.

**Worker delegation remains separate:** a generic MCP access token lacks the
existing signed real-flow-ID/command binding. It must not be forwarded as the
worker assertion or converted into a trusted `Principal` by copying claims.
The selected IdP/its existing authorized delegation facility must support the
already defined issuer handoff (for example, token exchange only if actually
supported and attested). Otherwise this remains an explicit delegation gate,
not grounds to add an assistant-controlled signing service. Exact-preview
approval/binding and capability checks remain in the existing DraftStore flow.
The stable admitted operation intent from the previous release fix must survive
HTTP reconnect/token refresh; a bearer JTI or shared client ID is not that intent.

**Real revocations have two inputs:** IdP subject/token/session withdrawal, and
operator consent/grant withdrawal. OAuth discovery of a `revocation_endpoint`
only describes where a client may revoke a token; it is not a subscription/feed
and does not prove current access-token status. Before admission, the real IdP's
reviewed current-state source (introspection or a supported authenticated event/
reconciliation path) must drive the SDK policy. Separately, a trusted administrative
identity applies the actual withdrawal to persistent issuer/subject/token/grant
tombstones in the existing authority store, with a confirmed monotonic checkpoint.
If upstream identity uses a different issuer/subject namespace from worker
delegation, attest an explicit mapping and preserve originating-token revocation;
never join by email or assume an OAuth JTI equals a worker assertion JTI. Feed
loss, sequence gaps, stale status and restart keep admission closed until
reconciliation. Existing 1–300-second worker freshness is unchanged. No timer
alone or successful login refreshes the checkpoint. No feed is claimed installed.

**Owner inspection completed 2026-10-28:** canonical checkpoint
`IRONMAN_TP_MCP_APP_AUTH_NONE_UI_20261028_V1` records supported authorization=None,
used authorization=None and DEVELOPMENT state for the existing dev app. Do not
ask the owner to repeat this inspection. The official update path and next future
UI action are documented below; no app settings have been changed.

Official references checked 2026-10-27:

- [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [Tunnel credential/header boundaries](https://github.com/openai/tunnel-client/blob/master/docs/architecture.md)
- [Tunnel HTTP bindings and OAuth discovery](https://github.com/openai/tunnel-client/blob/master/docs/connectors.md)
- [MCP OAuth 2.1 authentication](https://developers.openai.com/plugins/build/auth)
- [ChatGPT connection interface](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt)
- [Sign in with ChatGPT availability](https://help.openai.com/en/articles/20001410-sign-in-with-chatgpt)

CI, independent review, actual runtime access/configuration, protected state and
rollback, live identity/delegation/feed and provider canaries remain separate
release gates. This section supersedes the original migration preference for
stdio where a verified human approver is required; it does not propose public
HTTP or invalidate existing read-only stdio paths. No merge/deploy/TP write.

## Existing dev app update and prepared HTTP ingress — 2026-10-28

The official [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
guide, section **Refresh metadata**, explicitly covers changes to authentication
as well as tools/UI. It instructs the operator to deploy/restart the MCP server,
open the existing custom connection in ChatGPT Plugins, select **Refresh**, verify
the new metadata and test in a new conversation. It states that this flow applies
to custom MCP servers connected directly in ChatGPT. With the same tunnel ID and
connector-facing URL, changing only the private main binding does not require a
new app. This is the documented path for this dev connection; execution and UI
support on this account remain unverified until rollout, not assumed impossible.
No OAuth configuration is inferred from the current None/None display.

Do not confuse that path with the [submission portal](https://developers.openai.com/plugins/deploy/submission):
its advanced authentication comes from package mcp.json/uploaded versions; the
connection panel is not an advanced editor, and an existing OAuth client can lock
credential changes. Those are concrete restrictions on the packaged submission
flow, not proof this direct dev app must be recreated. Current documentation is
more specific than the older developer-mode article's generic published-app
limitations. No app recreation, package upload, reconnect/disconnect, credential
replacement, permission change or live Refresh was performed in this cycle.

The prepared factory is `tp_mcp.server.create_operator_http_app`, composed with
protected `OperatorHTTPConfig`, a real `OAuthMCPTokenVerifier` and a code-installed
`bindings_for(AccessToken)` factory. It returns an ASGI application for the SAME
SDK server; it neither opens a socket nor alters the default serve entrypoint.
Use existing runtime supervision when rollout is actually authorized. No new
service/unit, alternative MCP Server instance, job or operation manifest is
introduced. The existing SDK/Starlette dependencies are reused.

The native SDK manager uses stateless HTTP exchanges with JSON responses, not a
new session store. Identity is carried by the authenticated ASGI context into the
SDK's request dispatch, then into the existing operator handler and thread
launcher. Context resets after every request. Issuer + subject + client must match
the protected resource policy. Scope admission is not an approval or provider
permission. Before invoking the operator, the verifier runs again to account for
dispatch waiting; a withdrawn/expired token returns a standard OAuth linking
challenge. `bindings_for` cannot fall back to ambient stdio bindings. Actual
operation intents, grants, delegated worker assertions and persistent authority
continue to use their existing ports; bearer JTIs are never invented as intents.

Only `tp_ironman_request` is advertised and callable on this protected ingress.
Its descriptor advertises OAuth securitySchemes (including compatibility metadata).
Direct legacy tool calls and other resource/method access deny; adding the HTTP
transport cannot implicitly expose every old writer. Existing stdio descriptors
are not mutated. RFC9728 resource metadata and the 401 Bearer challenge are served
without authenticating a user; the issuer string is preserved exactly to avoid
URL-library slash normalization breaking OAuth issuer matching. No authorization
server/discovery proxy, signing key or production configuration is created.

The edge permits only loopback clients over an HTTPS ASGI scope, exact local Host
and same local Origin when supplied; DNS-rebinding checks stay enabled. Forwarded
IP/identity headers do not supply a principal. Duplicate Authorization headers and
bodies beyond 2 MB deny. Real socket binding/TLS certificates, trust/proxy policy,
rate limits and the tunnel's ability to reach the protected local endpoint must
be attested in runtime before exposure. ASGI tests enforce declared scheme/client
policy; they do not verify a real TLS handshake or the DigitalOcean service.

**New QA:** 16 focused tests pass with real SDK routing/ASGI and test-only signed
IdP/current-state policy. The two protocol paths (2025-11-25 and 2026-07-28) cover
OAuth discovery, a shared client with concurrent distinct humans, token renewal
and context delivery into the launcher stub. The new protocol uses its required
single-exchange envelope/method headers rather than the legacy initialize flow.
Other cases cover challenges, hidden legacy methods, forged identity metadata,
revocation while dispatch waits, missing binding despite an ambient stdio runtime,
unconfigured HTTP context, Host/Origin/remote/TLS/duplicate/body limits and feed
unavailability. No live network listener, provider request or Prefect flow ran.
Previous crypto/retransmission/in-process/multiprocess tests were not repeated.

**Autonomous operation after one setup:** keep identity middleware, token renewal
and revocation reconciliation automatic within the approved trust contract. The
IdP/OpenAI client must actually support automatic refresh (including appropriate
offline access policy if required); MCP does not store or fabricate refresh tokens.
Existing durable grants/bindings cover only the approved task/scope and must not
prompt for another manual handoff on every request/retry. Middleware rechecks are
internal checks, not new user approvals. Reauthentication, a genuinely new scope,
withdrawn consent or unavailable trust can still require a real authorization.

**Controlled future cutover, not executed:** first pass independent review/CI,
attest the actual IdP/resource/keys, current revocations, authorized delegation,
host binding factory, protected local TLS, existing API/runtime access and coherent
state/rollback. Test the local HTTP surface before changing the running tunnel.
Drain existing work without deleting claims/records; change the SAME tunnel's main
binding under existing supervision with no overlapping active stdio tunnel clients.
Do not move the connector URL or publish a new listener to bypass a restriction.
Then the owner's one planned interface operation is **Refresh on the existing
TrainingPeaks MCP connection, completing the initial OAuth sign-in if prompted**.
Verify Supported/Used authorization, unchanged app/tunnel identity and a fresh-chat
bounded check before calling the transition verified. No Refresh is needed now
while the server remains stdio/None; it would not supply the missing IdP.

Before OAuth cutover, the unchanged stdio setup remains operational. After OAuth
activation, rollback must preserve the authenticated ingress contract and current
revocations/operation state; close execution if a compatible rollback cannot be
attested. Do not silently downgrade to no-auth or erase approval/uncertainty to
restore availability. An incompatible authentication rollback is a release gate,
not an excuse to ask the owner for repetitive configuration changes.

The first real missing connection remains an existing attested IdP and current
revocation/delegation policies wired into the protected host composition. None is
configured by this commit. CI, independent review, runtime management and rollback
are separate gates. No new owner action is requested until its prerequisite is
ready; the completed None/None inspection is not reopened.
