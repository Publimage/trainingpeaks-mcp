# PR19 R-01: per-connection TLS and bounded admission

Prepared 2026-10-30 with AI assistance, on base
`7114d66f5481edf46da8482c5b2ec13a955a211a`.
This document describes a local candidate, not publication or release approval.

## Problem and change

Wrapping the listening socket performs the TLS handshake inside accept(), before
ThreadingHTTPServer dispatches a worker. One TCP peer without ClientHello can
therefore stop unrelated valid mTLS clients from being served. The prior isolated
review reproduced this on the exact base SHA; the remote PR was still at that SHA
when this work started.

The existing private bridge now uses a small ThreadingHTTPServer subclass in
`src/tp_mcp/bridge_tls.py`. It accepts TCP without TLS work in the accept loop,
then wraps the individual socket with `do_handshake_on_connect=False` and calls
`do_handshake()` in its connection thread. Only a successful handshake reaches
the existing handler. This is not an HTTP listener/fallback exposed to handlers.

The production defaults are:

- 5 seconds for the TLS handshake (the SSL handshake timeout covers the whole
  handshake, not a fresh allowance per incoming byte).
- 30 seconds of socket IO inactivity after the handshake, including idle HTTP
  keep-alive connections. This is not an absolute HTTP request or provider deadline.
- At most 32 admitted connections/handler workers per bridge process. A slot is
  reserved before spawning a worker and held through handshake and HTTP handling.
  Excess sockets are closed immediately, without waiting for capacity or emitting
  a plaintext response. Failures and normal exit release the slot.

The existing SSL context factory, mandatory CERT_REQUIRED, trusted CA, minimum
TLS version, certificate fingerprint/source binding and result-writer checks are
preserved. The subclass also refuses a context without CERT_REQUIRED. No workflow,
mutation gate, host trust configuration, service or TrainingPeaks operation was
changed.

Shutdown stops acceptance and signals/closes tracked TCP/TLS sockets, including
connections awaiting their worker. Ownership transfer from raw to TLS socket is
serialized with shutdown; the handshake itself never holds that lock. Existing
provider work is not forcibly cancelled. Pending OS reads have finite deadlines;
on Windows a buffered SSL read may finish at its IO timeout if the peer does not
consume EOF. Daemon workers do not make listener shutdown wait for those reads.

The cap prevents unbounded concurrent thread/socket allocation. It does not
guarantee availability under a sustained flood that occupies all slots, nor fairness
to legitimate clients during saturation. Network admission and production capacity
validation remain necessary. Authenticated clients sending data more frequently
than the idle timeout can retain a slot; no claim of complete slowloris protection
or interruption of provider calls is made.

## Verification actually performed

On Windows, Python 3.12, with disposable certificates and loopback sockets:

- `tests/test_bridge_tls_concurrency.py`: **12 passed**. Covers a silent TCP peer
  concurrent with a valid mTLS request; silent/partial TLS deadlines; bounded
  admission and slot reuse; idle authenticated HTTP timeout; shutdown/EOF; delayed
  worker startup racing shutdown; client not consuming EOF; thread-start failure;
  missing certificate and unpinned certificate; no plaintext fallback; rejection
  of a non-mTLS server context.
- Existing swim/client contract subset: **37 passed, 8 deselected**. Selected with
  `-k 'not real_http and not health_radar and not config_default and not
  unknown_provider_rejection_http and not existing_no_store'`. No live provider.
- Separate local harness: **8 checks passed** using the unchanged handler and
  startup function bodies extracted by AST, the actual new server class, disposable
  TLS contexts and counters instead of result persistence. Confirms actual handler
  service while a TCP peer is silent; no certificate/unpinned/source mismatch
  rejection; reader denial and writer success for both admin/radar sinks; startup
  wiring and close. This is not full application import or protected-host loading.
- Ruff on all `src/` plus all three changed/new test files: **passed**.
- Mypy on the new transport module with Linux platform and silent dependency
  following: **passed**. Full `mypy --platform linux src/` checked 59 files and
  reported one error: `private_bridge.py:226`, missing annotation for `clean`.
  Running mypy on that file from the unmodified base reproduces the same error.
  It is not introduced by R-01 and was not changed as part of this scoped fix.
- Python syntax compilation of the five changed/new Python files and
  `git diff --check`: **passed**.

The existing peer-authentication tests now instantiate the new server, using the
same protected-file PKI fixture. The fixture was split to expose the server SSL
context while retaining its original helper for other tests. These full application
tests, private-bridge and unified-bridge regressions could not be collected on
Windows because existing imports require `fcntl`. No fake flock or replacement of
POSIX security checks was used to report those suites green. They must run on the
actual supported POSIX environment before approval.

Local evidence is outside the repository under `review-evidence/`:
`r01-transport.xml`, `r01-swim-contract.xml`, `probe_r01_handler.py` and
`probe_r01_handler.results.json`. These are local evidence, not official CI.

## Publication and canonical checkpoint limits

GitHub independently confirmed PR19 head `7114d66f5481edf46da8482c5b2ec13a955a211a`,
branch `codex/ironman-preview-approval-20261026`, and base
`fix/ironman-unified-operator-errors-20261022` at PR18 head
`7fe73c25bc6a10940efcafd5d8eb726cf84524b7`. The local merge-base agrees.

A non-writing push authentication check failed because Git Credential Manager
could not obtain a username without prompting. No GitHub connector is installed.
No remote publication is claimed. Once access is restored, first recheck the PR
head, publish only if still appropriate, then verify the resulting SHA on GitHub.

Canonical Google Drive Knowledge Base documents, including the requested marker
`IRONMAN_PR19_SECOND_AI_REVIEW_TLS_ACCEPT_BLOCK_20261029_V1`, could not be read or
updated: the Drive integration is not installed and the in-app browser still shows
Google sign-in. A previous explicit refusal of Firefox control was not bypassed.
This local document is not a substitute for a saved and reread canonical checkpoint.

Official CI, real IdP/delegation, revocations, PKI, all-client TLS migration,
authoritative reconciliation, runtime configuration and backup/restore remain
separate open production gates. No merge, deploy, app refresh or TrainingPeaks write
was performed. Findings A-02/A-03/A-04/B-01 were not reopened by this change.
