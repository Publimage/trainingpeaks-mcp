# IRONMAN — TrainingPeaks MCP cloud migration / deployment gate

Status: **PROPOSED / PREPARED**, not deployed. Date: 2026-10-10.
Decision owner: the IRONMAN coach. Source of truth for project methodology: Google Drive `IRONMAN — KNOWLEDGE BASE`.
This file is a **technical implementation specification**, not a provider-release confirmation.

## Objective

Replace the Mac-dependent execution of `tp-mcp` + `tunnel-client` with a **private, single-tenant, always-on Linux runtime**, while keeping the existing GitHub repository and TrainingPeaks account boundary. Changes to the GitHub branch must be tested, deployed to staging, and promoted only after independent verification.

**Do not** use an unauthenticated public HTTP MCP endpoint, paste TrainingPeaks cookies/API keys in chats, Google Drive, GitHub, tickets or CI logs, or change live athlete calendars as part of migration.

## Minimal architecture (preferred pilot)

1. **DigitalOcean Basic Droplet**: Linux VM, 1 vCPU / 1 GiB RAM, official listed base price **USD $6/month**, before taxes/optional extras. Requires owner's connected billing account, cost approval and verification of the actual SKU before create.
2. **Single service host**: non-root service account; Python venv running this repository's existing `tp-mcp serve` stdio command; OpenAI `tunnel-client` run as a separate locked-down `systemd` service/sidecar. The OpenAI Secure MCP Tunnel documentation explicitly supports VM/systemd deployment.
3. **No public TrainingPeaks MCP listener/port**. The tunnel client initiates the outbound connection; restrict ingress to SSH for authorized maintenance, preferably key-based. Host firewall deny-by-default and unattended security updates.
4. **GitHub** remains code/version source. Deploy pinned commit SHA or signed release; never blindly pull arbitrary pushes into a process with TrainingPeaks write access.
5. **Secret source**: `Production_tpAuth` is a full-account credential. The existing client supports `TP_AUTH_COOKIE` for headless Linux; supply securely from an owner-managed secret or protected systemd credential, never bake into image/source or print it. Tunnel control-plane API key stored separately. Restricted filesystem permissions, no backup plaintext.
6. **Authorization**: keep existing MCP read/write guardrails, lab-only canaries, duplicate detection and readback checks. Existing TrainingPeaks browser-cookie authentication is not equivalent to stable official partner OAuth/API authorization; cookie expiry requires a secure refresh procedure and cannot be automated merely by moving servers.
7. **Connection**: first evaluate whether the existing tunnel registration/profile can move without a new app authorization. Never run two clients simultaneously against the same tunnel during cutover.

## Why not a public Python MCP endpoint as phase one?

The current MCP server is **stdio-only**. Publishing an HTTPS endpoint would require building and auditing Streamable HTTP transport, OAuth/authorization, strict host/origin validation, rate limiting and secret handling. A private VM+Secure MCP Tunnel avoids this extra security and implementation surface. Re-evaluate a public Streamable HTTP endpoint only after its auth provider and security testing are funded/approved.

## Release sequence — independent gates

**A. Source integrity (no provider writes)**
- Confirm the code, pinned branch/commit and dependencies; freeze the 35-note manifest and 19-native-strength manifest against Drive.
- Run lint, static typing and unit tests on an actual runner, retain logs/checks. A GitHub Actions workflow file is not proof that Actions is enabled; observed zero runs do not equal PASS.
- QA the custom `tp_sync_intermediate_native_notes` handler and dispatch, and reject failed/ambiguous tests.

**B. Pilot host provisioning (requires user action/billing and cloud access)**
- Verify connected cloud account and price; provision one instance only once approved.
- Apply least-privilege firewall, SSH, patching, monitoring, restart-on-failure and user separation. Do not expose TCP port for MCP.
- Install pinned code and Linux tunnel-client from official vendor distribution; verify binary signatures/checksums when published.
- Provision secrets owner-side without surfacing bytes to ChatGPT, GitHub Actions logs or responses.

**C. Staging authenticated read-only**
- Verify authenticated owner ID `2116886`; read libraries `3892900` (Note), `3891875` (Forza), target TEST plan `684602`, and exactly 35 approved native notes.
- Verify ChatGPT can discover the new `tp_sync_intermediate_native_notes` action after an app tool refresh / rescan. In a Business workspace, published custom MCP tool definitions can be frozen; code deployment alone may not expose new tools.
- Run `mode=preview` with zero writes.

**D. Native lab then publish (specific coach authorization already recorded; secure gates remain)**
- Run exactly one native `NoteTemplate` canary on `[MCP TEST] Integration Lab` `3890637`; verify actual `exerciseLibraryItemType=NoteTemplate`, title, body, ID.
- If LAB PASS, publish in small idempotent batches to `IRONMAN MASTER | Note` `3892900`. The first batch may be 1; verify each. Eventually require **35/35 native NoteTemplate** and zero duplicates.
- Separate tasks: native Strength Builder library 19 variants, README FIRST ordering, and two PDF attachments. None is automatically solved by creating NoteTemplates. Do not infer PDF propagation from copying notes.
- No changes to real athlete calendars or commercial plans during LAB cutover.

**E. Cutover and rollback**
- Compare new cloud outputs against old Mac connector in read-only mode before switching. Keep one active writer.
- Switch tunnel connection to cloud only after read-only parity and health checks, record exact server revision and responsible operator.
- Keep a rollback path to the Mac original if the cloud host fails; disable the cloud writer before failback to avoid duplicate writes.
- Set alerting for unauthorized authentication, repeated 401/cookie expiry, disconnect, provider API schema drift and duplicate POST risk. Stop writes on global credential/schema regression.

**F. Maintenance**
- Stage new commits, run real tests, deploy pinned revision, smoke-test read-only, then enable eligible writes.
- Add a durable task ledger/job queue in a later phase only when persistent background jobs are needed; a running MCP process alone does not create long-running jobs.
- Record PROPOSTA / INSERITA / VERIFICATA in Drive State and the matching provider IDs only after readback.
- Terms check: provider private-web/API routes should not be assumed permanently supported. Prefer official TrainingPeaks partner access when available.

## Financial and access prerequisites

- **Cloud provider account + billing** are not currently connected to this conversation. No cloud server has been purchased or provisioned.
- **Coach approval** of the small recurring infrastructure cost is needed before provisioning. The $6/mo example excludes taxes/backups and may differ at checkout.
- Never ask the coach to post TP login cookies, tunnel API keys, SSH secrets or passwords into chat.
- Google Drive (canon) and GitHub (code) remain unchanged as governing sources.
- `IRONMAN_TrainingPeaks_MCP_Aggiornamento_Sicuro.zip` in Mac Downloads is only an optional local updater, **not** a cloud deployment artifact; leave it unopened while pursuing the cloud route.

## References

- Official Secure MCP Tunnel: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- ChatGPT custom MCP app updates and frozen tool snapshot: https://help.openai.com/en/articles/12584461
- DigitalOcean Basic Droplet price: https://www.digitalocean.com/pricing/droplets
- TrainingPeaks current auth client: `src/tp_mcp/client/http.py`, `src/tp_mcp/cli.py`; first-class headless env `TP_AUTH_COOKIE` described in root `README.md`
- Canonical Drive docs: `00_IRONMAN_CORE_INDEX`, `01_MASTER_COACHING_CONTEXT`, `02_DECISION_LOG`, `03_OPEN_QUESTIONS_ROADMAP`, `20_TRAININGPEAKS_MCP_CONNECTOR_RUNBOOK`, `21_TRAININGPEAKS_MCP_INTEGRATION_STATE`.
