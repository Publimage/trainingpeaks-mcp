# IRONMAN Write Guard - Google Docs REST response contract correction

Status: source-only staging candidate; not deployed.

## Finding

The previous adapter incorrectly required a top-level `revisionId` in the response to `documents.batchUpdate`. The official Google Docs REST response carries the updated revision at `writeControl.requiredRevisionId`. The old fake API clients returned a nonstandard top-level `revisionId`, causing 86 existing tests to pass without verifying the real wire contract.

Official Google reference (verified 2026-11-01):
https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate

## Remediation

- GoogleDocsConnectorAdapter now requires a nonempty `writeControl.requiredRevisionId` from the native mutation response.
- Both local connector fakes emit the native response shape.
- Two negative tests reject the obsolete top-level-only response and an empty updated revision.
- DocsWriteGuard still requires its independent post-write `documents.get` readback to mark an operation VERIFIED.

## Evidence and limits

`python -m pytest -q` -> **88 passed** in the isolated code environment.
`python -m compileall -q *.py` -> PASS.

The preceding direct Google Docs connector canary was performed in an earlier step but did NOT invoke this Python adapter. Therefore: no new Google write or end-to-end ChatGPT -> Write Guard -> Docs execution is claimed here.

The Google Cloud service account, scoped sharing of a sacrificial Doc, HTTPS connector and prevention of direct-write bypass remain unconfigured. Do not treat this fix as a deploy or a new product release.
