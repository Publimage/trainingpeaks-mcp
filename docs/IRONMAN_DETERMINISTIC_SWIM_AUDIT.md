# Deterministic swim distance audit - isolated pilot

## Permanent placement and current status

- GitHub stores reviewed source code, tests and version history.
- The intended execution location is the existing Prefect worker on DigitalOcean, using a reviewed and pinned code revision. This pilot has NOT been installed there and is NOT yet called by a production workflow.
- The live Google Drive IRONMAN Knowledge Base remains authoritative for coaching method, product-specific rules and decisions. This code document is not a parallel methodological source.
- No module per new chat, no new server per checker and no provider-write permissions are needed for the validator itself.
- The draft PR is a review stage, not a deploy. A completed CI run would prove these tests only, not a server installation or full plan validation.

## What this validator proves

`audit_swim_distance(distance_planned, native_structure)` independently sums all supported native metre steps with their repetition multipliers. Timed steps classified as `rest` add zero metres. Easy swimming expressed in metres still counts even when classified as `rest`.

Outputs:

- `SWIM_DISTANCE_OK`: declared metres equal computed metres.
- `SWIM_DISTANCE_MISMATCH`: both totals are measurable but differ; the report includes the exact delta.
- `SWIM_DISTANCE_UNVERIFIABLE`: required data is absent, malformed or outside this pilot's supported schema. This blocks a successful check but does NOT establish that the underlying workout is wrong.

A PASS is ONLY a distance-arithmetic result. It does not approve recovery placement/presence, intensity, duration, graph coordinates, text agreement or physiological quality. Nested repetitions, yards, open-ended steps and active timed swim steps remain unsupported; they are not silently converted or inferred.

## Verification performed on 2026-10-22

The original module and test file were reproduced byte-for-byte against their Git blob hashes, and all 8 original tests were rerun successfully.

Three coach-owned library templates were read through the live TrainingPeaks connector. A field projection preserving every input consumed by this checker was tested locally; unused metadata and chart polyline were not included. All three distance totals matched (2500 m, 2200 m, 1200 m). For each sample, a negative control increased only the locally supplied declared distance by 100 m; all three mismatches were detected with delta -100 m. Source data was not mutated. These are library-template checks, NOT checks of the corresponding Training Plan copies or of all 24 weeks.

No timed-rest steps were present in these three live samples. Support for timed-rest arithmetic is therefore demonstrated by synthetic tests, not by this live sample. Manual comparison of one test description with its native structure found a prescribed timed recovery expressed in prose but not as a native timed step. The distance checker correctly remains PASS on distance alone; it must never be advertised as a recovery audit.

An additional malformed-input probe found a real OverflowError caused by converting a large integer to float. The code now handles integers exactly without float conversion, and rejects non-boolean `openDuration` flags rather than guessing their meaning.

The suite now contains 29 passing local tests (8 original plus 21 edge cases). The isolated GitHub Actions workflow is a separate verification step; consult its actual run result rather than treating this document as CI evidence.

## Safety and next integration gate

The module is a pure function: no network, credentials, file writes or TrainingPeaks access. Synthetic tests contain no private athlete or product payloads. Real sample identifiers and operational evidence belong in the private project checkpoint, not in public fixtures.

Before production integration: review the CI result, extend representative provider-schema coverage, define a separate recovery-prescription validator, then wire the reviewed version into an existing audit flow with an explicit distance-only result. No automatic merge, deploy, schedule, publisher registration or TrainingPeaks modification is authorized merely by a PASS here.

## Increment 2: separate recovery-prescription checker

`audit_swim_recoveries(spec, native_structure)` in `swim_recovery_audit.py` now checks stationary recovery duration, location in cumulative metres, order, repeated occurrences and zero native rest targets. It reuses the distance validator and generalizes the ordered comparison principle in PR13 without importing or modifying that product-specific generator or any provider writer.

The prescription must be independently supplied, not reverse-engineered from the structure being audited:

```json
{
  "schema": "IRONMAN_SWIM_RECOVERY_V1",
  "source_ref": "independent-reviewed-prescription:version-and-reference",
  "coverage": "complete",
  "total_m": 400,
  "pauses": [
    {"after_m": 100, "seconds": 20},
    {"after_m": 200, "seconds": 20},
    {"after_m": 300, "seconds": 20}
  ]
}
```

The source reference records provenance; it is not authenticated proof of approval. The production adapter must bind it to the approved source revision, workout identity and input fingerprint. This adapter is NOT yet implemented.

`complete` compares every stationary pause in order and can return PASS only for this narrow scope. `targeted` checks specific required pauses; success returns PARTIAL, never a full PASS. Missing requirements return FAIL; missing, malformed or unsupported input returns UNVERIFIABLE. All non-PASS statuses block a full validation gate. An explicit empty complete pause list represents a no-stop prescription; an empty targeted list is invalid.

No universal N versus N-1 rule is imposed. A final recovery passes only when explicitly prescribed. Metres labelled rest remain swimming and cannot satisfy a stationary pause. Text in a step name does not substitute for a timed native rest. Flexible duration ranges, open-ended recovery, active timed swimming and nested native blocks remain unsupported in this increment; no guessed values are substituted. A 10,000 expanded-step bound is computational, not physiological.

### Increment 2 evidence and limitations

38 new synthetic recovery tests passed locally. The CI workflow now runs these together with the 29 existing distance tests; actual CI completion must be checked separately.

The previously inspected test template was reread through the live connector. An independently transcribed targeted requirement was limited to its explicit five-minute pause after the easy swimming before the second test. The local projection of current native fields still passed distance arithmetic and failed the required pause check. Adding that one pause ONLY in a local counterfactual kept the metres unchanged and returned PARTIAL for the targeted check. This does not approve the whole workout or resolve the remaining interval-recovery prescription.

No private template payload, identity or complete prescription is stored in these public tests. The parser does not automatically understand arbitrary prose, and no complete plan audit, provider correction, merge or server deployment has occurred. Next gate: consolidate the two checks into one scoped report and verify an authorized read-only execution on the existing server before making them mandatory in production.

## Increment 3: combined report with versioned input bindings

`audit_swim_report` in `swim_audit_report.py` calls the two existing validators without changing them. It returns a single serializable report with separate binding, distance and recovery results. A successful targeted recovery check remains PARTIAL; unsupported data remains UNVERIFIABLE. A real detected failure stays visible even if another check cannot conclude. PASS means only that these two technical checks passed, never complete workout approval.

Required input contracts:

- Snapshot (`IRONMAN_SWIM_SNAPSHOT_V1`): `schema`, `target`, `distance_planned`, `structure`.
- Prescription envelope (`IRONMAN_SWIM_PRESCRIPTION_ENVELOPE_V1`): `schema`, `target`, `source`, `snapshot_sha256`, `recovery`.
- Target: `provider`, `owner_id`, `resource_kind`, `container_id`, `workout_id`, all explicit non-empty strings. Supported resource kinds are `library_template` and `training_plan_workout`; these are not interchangeable.
- Source: `source_id`, `revision`, `section`, all explicit non-empty strings. The existing `recovery.source_ref` must match `source_id`.
- Separate caller inputs: `expected_target`, `expected_source`, `expected_prescription_sha256`, `validator_revision` (full 40-character commit SHA).

The expected target, source revision and prescription digest must be obtained from the independently reviewed job manifest. Do not fill them by simply copying the untrusted envelope. The envelope binds the exact snapshot with a SHA256 fingerprint. The external prescription fingerprint binds the entire envelope, including source version and recovery contents. A changed source revision, workout, container, owner, resource kind, snapshot or prescription blocks the combined check before a success can be reported. A new fingerprint must never be silently generated to conceal a discrepancy.

The SHA256 helper uses sorted compact JSON, exact integer handling and no NaN/Infinity. The report is deterministic for identical inputs and does not mutate them. It records hashes, identity, source and the caller-supplied validator revision; no clock or file I/O is used.

### Trust boundary and what is still missing

These bindings establish internal consistency only. They do NOT authenticate a Google Drive source, prove it is the latest revision, prove coach approval, verify live TrainingPeaks ownership, or attest the actual executing code revision. `external_authenticity_verified` and `publishing_authorized` are always false. The report explicitly lists those limitations alongside physiological quality, total duration, graph and free-text checks that have not been performed.

The production source adapter must still read current canonical evidence through authorized connectors and populate a trusted job manifest. The runtime must separately verify its pinned code revision. A matching self-supplied hash is not a signature or authorization.

### Increment 3 evidence

40 new synthetic combined-report tests passed locally against byte-for-byte Git-blob-verified copies of the two existing validators. Tests cover wrong identities, library-versus-plan confusion, changed revisions, changed snapshot/prescription, malformed input, partial checks, explicit failures and input immutability. The unchanged 67 prior tests and these 40 tests are included in the updated CI workflow; consult the actual run and log for completion evidence.

No new TrainingPeaks live audit, provider write, merge, deployment, schedule or paid resource is part of this increment. The existing private source of truth remains Google Drive. The next step is the authorized source adapter and a pinned read-only server canary, not an automatic production release.

## Increment 4: acquisition using existing read-only interfaces

`acquire_swim_audit` in `swim_audit_acquisition.py` accepts a configured `GoogleDriveContextReader` (the existing Radar reader interface) and an already authenticated `TPClient`. It reads a canonical document and a coach-owned swim library template, re-reads both, and invokes the existing combined report. It does not create credentials, install software, schedule jobs or call a provider writer. This first acquisition adapter deliberately rejects Training Plan and athlete-calendar scope.

The request names one document ID/title/section, one complete library-template identity, an independently reviewed source-record SHA256 and the declared validator commit. The source text must contain exactly one JSON record between `[SWIM_AUDIT_BEGIN:section]` and `[SWIM_AUDIT_END:section]`. The record fields are `schema=IRONMAN_SWIM_SOURCE_RECORD_V1`, `target`, and the existing `recovery` specification. `recovery.source_ref` must be the selected document ID. Missing, malformed, duplicate-key or non-finite JSON is not interpreted or repaired. Source records and real identifiers remain private, outside this public repository.

The source-record hash is pinned independently before acquisition; it is never regenerated to accept an unreviewed prescription. The adapter then constructs the snapshot/envelope from the observed source version and provider fields. The envelope hash passed to the pure report is derived within this acquisition boundary after the independent source-record comparison; it is not a substitute for that comparison or for human approval.

Acquisition checks document identity/title, Drive numeric file version, content hash, a timezone-aware retrieval time no more than 300 seconds old, the actual library owner and the exact swim template identity. The timestamp threshold is an acquisition bound, not a coaching rule. It compares source version and bytes across the two reads, and the entire raw provider item across its two reads. Observed drift blocks the result; this is not an atomic transaction across providers or a promise that data cannot change after the final read.

Only the existing library GET routes are used. Native transport timeout/connection exceptions have at most three bounded retries at the same route. Permission errors, provider error responses and unclassified reader rejection are not blindly retried, and raw exception strings are not copied into reports. The three earlier validators are unchanged.

### Increment 4 evidence and remaining deployment gates

42 new tests passed locally using synthetic reader/client implementations and Git-blob-verified copies of the existing validators. They cover acquisition success, missing recovery, targeted checks, source/provider drift, ownership, wrong resource, reviewed hash mismatch, stale/future timestamps, malformed records, retries and immutable input. The updated CI includes these plus all 107 previous tests. Consult the actual CI log for the full-suite result.

These are integration-contract tests, NOT a new authenticated end-to-end Drive-to-TrainingPeaks run. The adapter supports the existing reader interface but has not yet been instantiated with the deployed Google reader and TP client. `external_authenticity_verified` and `publishing_authorized` remain false; the runtime must attest its reader configuration and pinned code separately.

Before the first live canary: register/review one private, explicitly targeted source record and test its exact exported representation (including any Markdown escaping); configure its independent record hash; provide the existing authenticated read-only dependencies; review/promote the code through the authorized deployment path; then execute and read back a bounded run on the existing server. Do not change the operator's trusted branch to run an unreviewed lab revision. Do not label a missing structured source as an incorrect workout, and do not imply that arbitrary natural-language prescriptions are parsed automatically.
