# IRONMAN Write Guard - staging runbook (v0.5 candidate)

**Status: code and loopback tests only. Do not expose this HTTP app publicly or change production Google Drive permissions.**

## Trust boundaries

- The incoming bearer secret lives in the ChatGPT plugin/connector's **trusted credential configuration**, never in the model's prompt or a tool argument. The server stores only its SHA-256 digest in a private config. Connections require HTTPS with a real certificate behind a reviewed reverse proxy; simple bearer auth is not appropriate over HTTP on public networks.
- The Google credential is obtained at the trusted host from Google ADC of an explicitly configured **dedicated service account** with access only to the selected staging file(s). No user OAuth token, static user refresh token or credential pasted into chat.
- A server-owned, 0600 config file provides actor, document allowlist and approval policy. Model-supplied policies, arbitrary API requests, endpoint URLs and access tokens in JSON are refused.
- SQLite journal must be on stable private storage with a single writer host. Mount and backup securely; no multi-host replicas until coordination is designed and tested. The `operations` table has no provider secrets.
- Keep the existing connected Drive tool operational during staging. Its direct write path is **not** blocked by this service. Restricting direct writes requires separate user approval, post-canary evaluation and a controlled permissions migration.

## Provisioning prerequisites

1. Obtain explicit operator-approved Google Cloud project/service account with Docs API enabled. Verify its identity and grant access only to an isolated test document (not the V1 Knowledge Base). This is a configuration dependency, not proof that any user action is currently required.
2. Configure a service-managed Google ADC credential, preferably through an approved workload identity. The current code asserts the service-account ADC type and principal email; it intentionally rejects other credential types. The host must provide this without exposing private key material in GitHub, ChatGPT messages or the ZIP.
3. Generate a high-entropy independent ingress bearer token in the operator's secret manager and configure only its SHA-256 digest in `WG_CONFIG_PATH`. Set file mode 0600; rotate/revoke by changing the service configuration and restarting. This approach is a staging mechanism; a reviewed OAuth client/identity-aware proxy is recommended for future production.
4. Set `ledger_path` to an absolute private persistent path with restricted OS permissions. Both ledger and secrets must be excluded from source control and backup dumps accessible to untrusted actors.
5. Configure a standing scope of one **sacrificial Docs ID** with short expiration; or use reviewed signed approval configuration for larger mutations. The request cannot name its own security policy.

## Example shape (not live; placeholders, never paste real secrets into chat)

```json
{
  "actor": "staging-operator",
  "service_account_email": "SERVICE-ACCOUNT@PROJECT.iam.gserviceaccount.com",
  "ledger_path": "/var/lib/ironman-write-guard/operations.sqlite3",
  "bearer_token_sha256": "<64-lowercase-hex-digest-generated-by-the-operator>",
  "allowed_documents": ["<isolated-disposable-doc-id>"],
  "standing_policy": {
    "policy_id": "staging-checkpoint-v1",
    "actor": "staging-operator",
    "allowed_documents": ["<isolated-disposable-doc-id>"],
    "expires_at": "<future-UTC-ISO-timestamp>",
    "max_replacement_chars": 1600
  }
}
```

## Run (only after operator config is provisioned)

```sh
python -m pip install -r requirements-runtime.txt
export WG_CONFIG_PATH=/path/to/private/staging_config.json
python staging_server.py
```

Listens only on `127.0.0.1:18765` by default. `GET /health/live` means process alive, **not** provider readiness. Require authentication on all functional paths. Inbound `POST /v1/docs/replace` supports only one exact tab-text replacement with fixed capability; `GET /v1/operations/<id>` allows a new client session to inspect the SQLite ledger. Nothing in the JSON body can provision, expand or bypass permissions.

## Test protocol

- Safe auth-negative tests without any real Google identity: missing/bad bearer -> 401 and zero provider factory calls; out-of-scope document -> 403 before factory; unknown input fields -> 422; `/health/live` -> running only.
- Isolated provider canary once approved: create/inspect sacrificial Docs ID, record revision, make one additive marker replacement through the **full** inbound endpoint, verify the Docs response and independent provider readback, then call `/v1/operations/<operation_id>` from a separate client. Repeat identical request, confirm no second write. Send a changed payload with the same operation ID and observe conflict. Test stale revision on a separate unique operation.
- Crash/recovery, bad tokens, expired standing policy, provider HTTP 403/429, offline/timeout and audit sampling must be separately validated against the staging runtime, not extrapolated from local fakes.
- Revoke the test policy; delete temporary test document after provider readback; rotate bearer and remove test account access. Never use the canonical Knowledge Base as the canary target.

## Still open

A functioning ChatGPT connector action requires an approved registered plugin/custom connector configured to call the HTTPS staging endpoint with a secure credential; no such plugin is installed by this package. Workload identity or service-account ADC and the outbound Google Docs authorization are not configured here. No end-to-end guard -> Google Docs authenticated live provider write has occurred. Write Guard is optional until a separate reviewed permissions change removes other write paths. Treat these as release gates, not as a reason to stop unrelated supported work.

## v0.6: independently signed approvals and read-only service-account preflight

The runtime configuration now accepts exactly **one** of `standing_policy` and
`signed_policy`. The latter is operator-controlled and supports an already
independently approved, signed patch without passing the signature, HMAC key,
or policy in HTTP request data. It **does not create approvals automatically**.

```json
"signed_policy": {
  "keys_file": "/etc/ironman-write-guard/private/trust-keys.json",
  "approvals_file": "/etc/ironman-write-guard/private/approved-patches.json"
}
```

`trust-keys.json` is a JSON object mapping `key_id` to a hex-encoded random
HMAC secret of **at least 32 bytes**. `approved-patches.json` is a JSON list
of records with exactly `approval_ref`, `patch_digest`, `actor`, `expires_at`,
`key_id`, and `signature`. Only the trusted operator's signature generator may
create those records. Every file must have a secure private parent directory,
be owned by the service user, not be a symlink, and have mode `0600`.
Never store real key bytes or approvals in GitHub, Library, Drive, or chat.

After the service identity is provisioned, run an **isolated, read-only** probe:

```
WG_CONFIG_PATH=/etc/ironman-write-guard/private/config.json python provider_preflight.py
```

Success means the **dedicated** Google credential is available and the specific
allowlisted document(s) can be read. The output includes only masked document
suffixes and revision hashes; it never prints text, access tokens, or the actual
credential. It does **not** certify a provider write. Missing ADC returns
`GOOGLE_IDENTITY_UNAVAILABLE`; inaccessible Docs returns
`GOOGLE_DOCUMENT_UNAVAILABLE`. Do not treat either as a security policy denial
without checking the actual provider/IAM error source.

The Google Drive plugin connected to ChatGPT can already read/write Google
Docs, but its OAuth credential is not exported to this separate Python
service. This package cannot create a Google Cloud service account or
register a production ChatGPT plugin on its own. Setup must be performed by
an authorized operator via the official cloud administration workflow and a
registered HTTPS endpoint. Until then, keep staging *not deployed* and leave
existing workflows unaffected.
