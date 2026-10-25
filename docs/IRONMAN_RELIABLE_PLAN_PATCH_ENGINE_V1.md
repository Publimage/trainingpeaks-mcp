# IRONMAN Training Plan write-engine v1 — development branch only

## Purpose

Replace repeated one-off scripts for *existing plan workout patches* with a single
provider-neutral, reviewed-manifest engine. This version handles selected-field
updates of **existing workout copies** and protects other workout fields by
copying the entire original provider object before changing only the selected
keys. Training Plan instances, athlete calendars, and Workout Libraries remain
separate resources.

**This is not deployed or registered as an MCP operation.** It must not be used
as a substitute for a platform authorization denial. It requires code review,
provider adapter validation, a controlled LAB write, and an independent readback
before production use.

## Supported operation

`scripts/ironman_jobs/plan_patch_batch_core.py` exposes an asynchronous
`run_batch(manifest, gateway, journal_path, execute=False, ...)`.

The caller supplies a trusted PlanGateway with `get_owner_id`, `get_plan`,
`get_workout`, `put_workout`. This module contains no network implementation
and accepts neither shell commands nor arbitrary provider endpoints.

Allowlisted fields:

- `title`
- `description`
- `totalTimePlanned`
- `distancePlanned`
- `structure` (complete validated Builder with polyline)

The manifest is a reviewed immutable JSON document; an executor requires both
`ack_scope` and the exact `reviewed_manifest_sha256`. A general permission to
change plans is **not** a substitute for these safeguards.

Example (synthetic LAB only):

```json
{
  "schema": "IRONMAN_PLAN_PATCH_V1",
  "owner_id": 2116886,
  "plan_id": 777,
  "expected_title": "LAB | Release candidate",
  "expected_is_public": false,
  "expected_workout_count": 2,
  "scope": "trainingpeaks:lab-plan:777:patch-1-approved-description",
  "items": [{
    "workout_id": 11,
    "before": {"description": "Old text"},
    "after": {"description": "Updated text"}
  }]
}
```

## Execution contract

1. Validate manifest schema, scope, title, visibility, owner, count, IDs, field
   allowlist and destination-specific Swim duration + distance gates.
2. Preview by default, always with zero provider writes.
3. On approved execution acquire a cross-process lock and match reviewed digest.
4. Read each target from the provider. Already-matching targets are verified and
   skipped. Any unexpected value causes a stop rather than overwriting it.
5. Save a private, mode-0600, crash-persistent journal and the original provider
   workout before the first write.
6. Apply only selected fields, read back, and mark VERIFIED only on exact match.
7. If a write raises an exception, independently read the provider: if the desired
   state is present, treat it as verified; otherwise mark UNCERTAIN and stop with
   **no blind replay**. A later readback of an already-correct item may reconcile
   automatically; an uncertain item still in its original state requires review.
8. Reread targets and plan invariants at the end. Preserve public state when the
   reviewed manifest targets an already-public plan.

## Current boundaries

This component is an isolated library and has **no provider adapter wired in**.
It cannot itself publish a Training Plan, insert native Strength Builder objects,
attach PDF guides, change prices, add notes, or expose a generic mutation tool to
ChatGPT. Those require separate provider-specific, reviewed implementations and
integration tests. It also does not currently perform a full non-target-workout
diff: the provider-specific integration must add that check when warranted.

A previously refused write does not become authorized because this library exists.

## Verification

Unit tests:
`pytest -q tests/test_plan_patch_batch_core.py`

These cover read-only preview, digest/ack gates, public-plan preservation,
replay-free retries, ambiguous outcomes, concurrent writers, drift, journal
binding, Swim gates and broken literal newlines.

Status: **IMPLEMENTED IN REVIEW BRANCH; PROVIDER DEPLOYMENT NOT DONE.**
