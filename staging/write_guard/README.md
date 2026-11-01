# IRONMAN Write Guard — engineering prototype v0.4 (2026-11-01)

**State: OFFLINE POC — NOT PRODUCTION, NOT DEPLOYED, NO GOOGLE CREDENTIALS.**

V1 Google Drive Knowledge Base is the canon. V2 remains staging. This package does not write to any external services and is not a new Knowledge Base. Real provider writes require a separately reviewed adapter, independent authentication and authorization, and deployment gates.

## Problem being solved

An assistant can read a Proven Path and still omit it in a subsequent write operation. Prompts and long documents cannot enforce a safety or reliability contract. A backend gate must execute checks as code and provide observable outcomes.

## Proven Path does not equal a new certification for each request

Capability routing is by **resource + operation class**, not by new path label or document. The existing `google_docs / replace_text_once` capability resolves `AUTO` to `DRIVE-DOC-004` (the relevant resource-class Proven Path). A different authorized Google Doc uses this same capability without a new named certification.

Unknown capabilities are not global blockers: they return `VALIDATION_REQUIRED`; offline-tested candidates return `CANARY_REQUIRED`. A canary requires properly scoped approval and independent readback on a sacrificial resource before real production rollout. No offline test, LLM text, or forged path label promotes an unknown writer to `VERIFIED`.

## POC guarantees tested

- Validates complete operation scope and checkpoint uniqueness; authorized target allowlist.
- Fake independent authorizer checks **the entire proposed mutation** (not just document ID and operation ID); live policy service is future work.
- Version precondition is checked before and **must be enforced by the provider adapter** during the write.
- Persistent SQLite journal is committed **before** the external side effect. State machine: `IN_FLIGHT`, `VERIFIED`, `FAILED_NO_CHANGE`, `UNCERTAIN`, `SECURITY_DENIED`, `UNCERTAIN_SECURITY_DENIAL`.
- Idempotency key and payload digest prevent duplicate writes and changed-payload replays.
- Post-readback is required to report verified success. A timeout after an actual write is recovered by readback.
- A provider read outage persists an uncertain state. A fresh process can reconcile later.
- An explicit confirmed denial is recorded, and that same operation is not retried or redirected elsewhere to bypass the denial.
- Genuine process termination after a local fake provider write is tested via an actual child process and `os._exit`.

## Run tests

```sh
cd /mnt/data/ironman_write_guard
python -m pytest -q
python -m compileall -q guard.py routing.py test_guard.py test_routing.py test_process_crash.py
```

**Result in this session: 31 tests passed.** All provider adapters used in tests are local fakes. No live end-to-end test exists yet.

## Correct engineering lifecycle

1. **Inventory and classify** existing write surfaces and real Proven Paths, including source revision and execution evidence. Do not duplicate existing paths.
2. **Threat-model and review** the trust boundary. An LLM must not supply its own proof of authorization, capability verification, or provider credentials.
3. **Build a provider-specific adapter** (start with Google Docs) with real IAM/OAuth scopes, enforced document revision and explicit response validation.
4. **Connect the gate to one supported write surface**, remove/limit bypass permissions where technically feasible and approved. Otherwise the gate is *optional*, not enforced.
5. **Stage and canary** a specifically approved sacrificial document with independent readback, crash testing, conflict tests, stale revisions, duplicate requests, real network timeouts and permission failures.
6. **Use CI and peer review** with negative tests, diff review, exact immutable release SHA and rollback. Production change is a separate explicit approval.
7. **Monitor with real indicators**: readback-confirmed success; unreconciled operations; duplicate prevention; error classification; operator interventions; coverage of routed writes vs bypassed writes. Record actual metrics, never invent them.
8. **Roll out gradually**, beginning with Docs only, then separate TrainingPeaks, Social MCP and GitHub adapters. Preserve provider-specific release and approval gates.

## Critical gaps (NOT solved)

- Current `DOCS_CAPABILITIES` is an **offline illustrative constant**. A production capability registry must be trusted, versioned, tied to a real provider operation and validated evidence. Accepting a registry object from an LLM would defeat the design.
- `FakeAuth` is **not a production authorizer**. Service identity and approval grants must bind actor, scope, target, mutation digest, expiry, and revocation.
- SQLite is safe only for a shared local host. Multi-host deployments require a distributed coordinator, lease management and replay-safe provider operations.
- `IN_FLIGHT` with no post-write evidence needs explicit reconciliation or a proven provider CAS/idempotency mechanism. This POC **deliberately does not blindly retry**; it is not yet a self-healing production system.
- No real Docs adapter or permissions segregation, no true enforcement across direct ChatGPT connectors, no CI run on GitHub, no prod or staging deployment, no monitoring dashboard, no rollback exercise.
- Neither a path name nor a test count proves that providers will never deny a future request. Security decisions are preserved; engineering prevents *avoidable* errors and scopes unavoidable denials to one operation.

See `ENGINEERING_DECISION.md` for review gates and objective acceptance criteria. Do not deploy this ZIP as-is.

## 2026-11-01 v0.3 prototype increment (not a production release)

The prototype now includes `google_docs_adapter.py` with a Google Docs native request contract plus paragraph-only/tab-scoped safety checks. **43 tests PASS offline.** A separate authenticated Google Docs canary verified the provider-side `requiredRevisionId` and one-change readback; its disposable document was subsequently deleted. See `GOOGLE_DOCS_CANARY_20261101.md`.

Important: this is **not** a service installation or an end-to-end authenticated guard. The Python guard has not been wired into the connector runtime and cannot constrain direct ChatGPT connector tools yet. The next professional milestone is a reviewed, authorized bridge and dedicated service identity, then one full guard-to-provider canary. No credentials are stored in this package.


## 2026-11-01 v0.4: authenticated service-account bridge (CODE READY; NOT CONNECTED)

The code now includes `authenticated_bridge.py`, an API bridge designed for a **dedicated server-side Google service account** rather than for a ChatGPT connector token. It builds the actual Google Docs REST contract (`documents.get` with tabs; `documents.batchUpdate` with `writeControl.requiredRevisionId`) and uses `google.auth.default()` and `AuthorizedSession` in the trusted runtime. It verifies the **expected service-account principal**, denies arbitrary URLs, rejects unsupported mutations, and classifies HTTP 403 as an explicit denial for the exact operation. Credentials and signing keys are NOT supplied here.

Two **independent** authorization patterns are supported:

- `SignedApprovalAuthorizer`: trusted short-lived, signed approval linked to the full patch digest, actor and expiry. The signer must be a separate trusted service, not an LLM or a file the LLM can edit.
- `StandingPolicyAuthorizer`: reusable server-approved policy for **small additive checkpoint replacements** on an explicit document allowlist. It does not require a separate approval per target, and rejects deletions, oversized changes, unexpected documents and expired policies. Only the service owner can provision this policy; it is not generated from a chat.

These are *different approval scopes*, not two escape paths after a denial. For any invocation, the service selects its preapproved policy and logs the operation under the same SQLite guard. New resource-class capabilities still require targeted validation; routine documents use the already verified Docs write capability. No existing Google Docs tool must be bypassed to evade a security denial.

### Running locally

```sh
cd ironman_write_guard
python -m pytest -q
python -m compileall -q .
```

All offline tests (including a deterministic fake HTTP transport) pass. The live canary in `GOOGLE_DOCS_CANARY_20261101.md` is evidence for Google Docs *provider semantics only*, not for an authenticated Python-to-Google invocation. This environment has no Google ADC principal and no runtime bridge registered with ChatGPT; the v0.4 Python bridge has NOT made any live Google calls.

### Before integration/deployment

1. Provision an independent service identity by the environment owner; share only the authorized staging document(s) with that identity. Keep credential material in the hosting secret store (prefer workload identity where available; this POC deliberately requires a dedicated service-account ADC type). Do NOT paste keys into ChatGPT or commit them to GitHub.
2. Implement the trusted issuer / standing-policy configuration lifecycle and authentication for the **inbound** ChatGPT-to-service request. Record scope, actor and revocation; only an authorized operator can change policy. This POC does not contain a public HTTP or MCP endpoint yet.
3. Deploy first to isolated staging with a durable, access-restricted ledger and provider-level readback; verify crash/restart and a scoped canary through the **entire guard**, rather than just Google Docs directly.
4. Only after successful end-to-end review, expose a minimal scoped MCP/plugin action to ChatGPT; prevent direct bypass only through a reviewed permissions/configuration change with user approval. Existing connected Google Drive tools remain usable independently until then, so no claim of mandatory enforcement is justified.
5. Keep V1 Knowledge Base canonical, V2 staging. The deployment is not itself a Knowledge version promotion.

Current status: **64 offline tests PASS. API bridge coded. No Google ADC bound; no inbound ChatGPT connector, no live end-to-end test, no deployment, no permission changes.**

## 2026-11-01 v0.5 candidate: minimal inbound HTTP entrypoint, NOT deployed

`inbound_api.py` exposes an intentionally narrow FastAPI HTTP interface: authenticated `POST /v1/docs/replace` and `GET /v1/operations/{operation_id}`. A bearer credential is verified **before** any Google service/account construction. Service-only configuration supplies allowed document IDs, actor, standing policy and Google principal; requests cannot supply credentials, policy JSON, arbitrary Proven Paths or generic Google Docs API calls. Successful operations are persisted by the existing SQLite journal and visible to a fresh authenticated client.

`staging_server.py` binds only `127.0.0.1:18765` by default. `STAGING_RUNBOOK.md` describes the operator-provisioned ADC and private policy config, HTTPS/reverse-proxy and future custom connector needed to expose this capability in ChatGPT. The runtime has not been deployed or connected; no Google credentials are included. Local tests are provider fakes and simulated HTTP transports; do not mistake them for a real authenticated Google Docs end-to-end canary.

### 2026-11-01 revision: v0.6 security/readiness completion

This incremental source package fixes a v0.5 deployment gap: trusted runtime
loading of independently signed, patch-bound approvals from private on-host
files. It also adds `provider_preflight.py` for bounded **read-only** checks of
service account identity and document access. The real ChatGPT Google Drive
connector's OAuth credentials cannot be reused by Python; no identity,
Google API write, cloud deployment, plugin registration or bypass-lock has
been made by this release. Test count: 86/86, local fakes and local HTTP only.
See `STAGING_RUNBOOK.md` for authorization-mode examples and truthful gates.


### Development-source correction, 2026-11-01 (no deployment/version promotion)

The Google Docs adapter now handles the actual REST `documents.batchUpdate` response `writeControl.requiredRevisionId`, rather than the incorrect top-level `revisionId` used in prior test fakes. The test suite passes 88/88, including two new negative contract tests. See `GOOGLE_DOCS_REST_CONTRACT_FIX.md`. The authenticated service-account end-to-end canary remains pending.
