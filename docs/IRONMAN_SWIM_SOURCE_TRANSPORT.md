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
