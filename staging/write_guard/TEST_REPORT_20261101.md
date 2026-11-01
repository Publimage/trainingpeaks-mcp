# Write Guard v0.5 candidate - execution and integration summary

Date: 2026-11-01. Scope: local code and loopback HTTP staging entrypoint only.

Code baseline: inherited v0.4, 64 offline tests PASS. New files: `inbound_api.py`, `test_inbound_api.py`, `staging_server.py`, `test_staging_loopback.py`, `STAGING_RUNBOOK.md`. Existing source untouched except local README/requirements. Python test run: **78/78 PASS**, including a real loopback HTTP server in a terminated child process. Compiler `compileall` passed.

New checks: server-side bearer SHA256 equality before connection factory; unauthorized cannot initialize Google credentials; full request model prohibits arbitrary target URLs, policy, tokens or custom Proven Paths; actor and standing policy are server-owned; trusted config file mode 0600; unknown document ID rejected; operation status endpoint survives a new request with ledger persisted; one fake Google Docs update and duplicated request produce one write; explicit provider 403 gives persistent no-retry; wrong payload same id gets conflict. Live localhost HTTP test: no token -> 401; with valid token but **no Google ADC** -> 503 (closed); no ledger or provider write.

**NOT PROVED**: production security posture, TLS proxy, actual Google service-account identity, connected ChatGPT custom plugin or real MCP caller, full Write Guard -> Google Docs provider canary, crash between remote API write and provider readback, remote ledger backups/restore, forced use/no bypass by ChatGPT, coverage for TP or Social. G4/G5/G7/G8/G9 remain open. Direct Google Drive connector remains independent and working; never shut it off pre-canary.

Deployment prerequisites and scope gates are documented in `STAGING_RUNBOOK.md`. The bearer token and service-account credential must be operator provisioned, never pasted into chat or included in the artifact. The local staging server binds 127.0.0.1 only. Source artifact is not a release and V2 remains staging, V1 remains canonical.
