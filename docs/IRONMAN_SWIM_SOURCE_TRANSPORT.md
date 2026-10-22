# Swim source transport: exact plain text

## Observed integration defect

An actual authenticated export of the private canonical sample on 2026-10-22
showed that Google Docs Markdown export escapes square brackets and underscores.
The strict acquisition parser therefore cannot find its exact markers; escaped
JSON keys would also no longer constitute the expected record. The private
payload and document identifiers are intentionally absent from this repository.

This supersedes earlier instructions to feed the Radar reader's default
Markdown export directly to the swim acquisition adapter. The Radar reader and
its users remain unchanged.

## Reader for this acquisition path

Use `GoogleDriveSwimSourceReader` from `swim_audit_drive_reader.py`. Supply an
already authorized Google session with Drive read-only access. This reader
implements `read_document(spec)` and explicitly requests `text/plain`. It does
not load, copy or log credentials and has no provider write method.

Metadata is read before and after export. Document identity, native MIME type,
trash state and version are validated. Observed version or modification-time
drift rejects the read. Exact UTF-8 bytes are hashed without unescaping,
replacing punctuation, correcting JSON or changing the approved digest.
Redirects are not followed. Access denials are typed separately from transport
failures; the existing acquisition layer owns bounded retries. Rate limits and
other non-success responses stop rather than guessing an alternate route.

Example composition in a reviewed runtime:

```python
reader = GoogleDriveSwimSourceReader(existing_readonly_google_session)
result = await acquire_swim_audit(
    independently_reviewed_private_request,
    drive_reader=reader,
    tp_client=existing_authenticated_tp_client,
)
```

The runtime must provide both dependencies in an authorized execution path;
this example is not a deploy command. The independent prescription pin must be
fixed before readback, not recalculated to accept a changed source.

## Evidence and limits

A canonical targeted sample was inserted in the existing private Drive KB and
read back through both actual export formats. Plain-text markers were unique,
its JSON parsed without modification, and its canonical record SHA256 matched
the pin calculated before insertion. Markdown did not preserve those markers.
This is real connector/export evidence, not a live server execution of this
Python reader or of the complete acquisition/report pipeline.

35 reader tests ran locally. One additional CI test joins the new reader to the
existing acquisition source contract and strict parser. These use synthetic
HTTP responses; consult the actual CI run for the combined suite result.

No swim code was merged, installed on Prefect or scheduled. No TrainingPeaks
workout was edited. A separate existing READ_ONLY server inventory succeeded;
it does not establish a completed swim canary. Authenticated source acquisition,
provider transport, pinned runtime execution and result readback remain required
before claiming an end-to-end server result. `publishing_authorized` and
`external_authenticity_verified` remain false in the existing report.

## Two-server transport added in the same draft PR

The existing private bridge serves Radar input, not Workout Library templates.
The Google read-only session belongs on Prefect; the TrainingPeaks session
belongs on the TP server. Do not copy either credential to the other server.

`src/tp_mcp/swim_audit_bridge.py` adds a bounded data reader and a client adapter.
`private_bridge.py` wires `POST /v1/swim-audit-input` into the existing listener.
This POST only submits a read request to our bridge; all TrainingPeaks operations
are GETs through the already authenticated TPClient.

Activation requires a separate server-local `allowed_swim_templates` list,
containing exact provider, owner, resource kind, library and template identities.
It defaults to an empty list. The athlete allowlist does not authorize library
reads. Both the existing source-IP boundary and this separate allowlist apply.
The connected person ID and library owner must match before an item is returned.
Unknown templates are denied before opening the provider client.

Only the item's identity, sport/type, planned distance and native structure are
transported. Other templates, free descriptions and attachments are not exported.
The envelope is marked `AUDIT_FIELDS_V1`: its digest is an audit-field projection,
not proof that every field of the entire original workout remained unchanged.
In the existing acquisition report, `raw_template_sha256` therefore hashes this
returned projection when this transport is used. Source and template are still
re-read; each adapter GET obtains a fresh bridge response, without a cache.

On Prefect, the narrow composition becomes:

```python
from tp_mcp.swim_audit_bridge import SwimAuditBridgeClient

result = await acquire_swim_audit(
    independently_reviewed_private_request,
    drive_reader=GoogleDriveSwimSourceReader(existing_readonly_google_session),
    tp_client=SwimAuditBridgeClient(independently_reviewed_private_request["target"]),
)
```

The client only supports the two existing library read paths. Its HTTP destination
is fixed to the existing VPC bridge, with no redirects or environment proxies.
Response size is bounded and the envelope's identity and read timestamp are
validated. Explicit access denial and unclassified provider rejection do not
become retryable connection errors. Only typed transport failures use the
acquisition layer's existing bounded retry policy.

This preserves the existing private-network/source-IP trust boundary. It does
not add cryptographic peer authentication, TLS, administrative execution or a new
public port, and must not be described as doing so.

## Test evidence and remaining operational blocker

45 new transport/handler tests passed locally, including a real localhost HTTP
listener with synthetic provider data, default-off behavior, no provider access
on denied targets/sources, and preservation of health/Radar behavior and no-store.
Three additional CI cases compose the bridge with the existing acquisition and
report validators: complete prescription -> PASS; targeted -> PARTIAL; missing
pause -> FAIL. These are synthetic cases, not the private live CSS template.
The CI workflow retains all prior tests; check the exact revision/run for results.

No configuration, service, listener or deployment on either real server is changed
by this draft PR. No new keys, paid resources, provider writes, operator jobs,
admin-agent operations or Radar schedules were introduced.

The runtime gate remains OPEN: review/promote the code; deploy it through an
authorized path; enable only the privately reviewed canary target; execute the
composition on Prefect with its existing Google session and pinned code; retain
and read back the resulting report. Merely reaching the SSH port, testing on CI,
or running an unrelated TP-side inventory does not close this gate. The current
connected DigitalOcean toolset does not expose command execution inside Prefect;
an authorized execution path there must actually be available before a live run
can be claimed. Do not repurpose fixed Radar administration actions as a shell.
