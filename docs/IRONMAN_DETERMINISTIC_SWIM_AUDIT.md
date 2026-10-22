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
