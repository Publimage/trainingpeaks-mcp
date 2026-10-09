# TrainingPeaks native Training Plan — six-Other cleanup gate

Date: 2026-10-09. Experimental scope ONLY:
- Private, unpriced plan `684463`: `[MCP TEST] IRONMAN Intermediate 24W - Archive Pilot`.
- Start date: `2027-01-04`.
- Preserve 13 training workouts, 8 native notes and the plan start date.
- Published Beginner plan `679801` and all athlete calendars are absolutely excluded.

## Current provider state (read back on 2026-10-09)

19 entries in the Training Plan: 13 real workouts and 6 legacy one-minute `Other` cards.
8 native TrainingPeaks calendar notes already exist, matching the six legacy editorial cards
plus two additional W3/W4 notes. **No real DELETE has been performed**.

## New independent endpoint evidence

The 2026-07-04 `wattgod/gravel-race-automation` Training Plan architecture
records this route in a "TP-build automation — PROVEN" section:

`DELETE /plans/v1/plans/{plan_id}/workouts/{workout_id}`

Source: https://github.com/wattgod/gravel-race-automation/blob/main/docs/TRAINING_PLAN_MARKETPLACE_ARCHITECTURE.md

This is credible independent evidence for the *candidate* Training Plan-specific
route, distinct from `/fitness/v6/athletes/{athlete_id}/workouts/{workout_id}`.
It is NOT yet a locally captured successful DELETE against a disposable plan.
**Do not treat research evidence alone as a production authorization.**
The hard safety gate `_VERIFIED_PLAN_WORKOUT_DELETE_TEMPLATE=None` remains in place.

## Implemented, non-destructive diagnostics

The existing `tp_get_training_plan_workouts(plan_id=684463)` tool now returns
`legacy_other_cleanup_readonly` on the experimental branch, including:
- Each of the six approved title/date pairs and the number of matching old cards.
- Native-note exact title/date/body match and its note ID.
- Workout ID and the provider identifier fields, **only if the provider supplies them**.
- True workout count, old Other count, native note count, and route verification status.

The staged `tp_delete_training_plan_other(plan_id, expected_title, dry_run=True)`
also returns a protected preflight. `dry_run=False` is deliberately blocked
with `DELETE_ROUTE_UNVERIFIED`, without calling the provider DELETE endpoint.

The native note ID reader supports provider keys `id`, `calendarNoteId`, and
`noteId`. Tests cover each key. The test branch has no confirmed Actions
workflow runs; do not claim tests PASS before running them.

## First gate: local tests and MCP refresh (not completed remotely)

On the coach's Mac:
```bash
cd ~/trainingpeaks-mcp
git status --short
git switch feat/mcp-test-training-plan-lab
git pull --ff-only
source .venv/bin/activate
python -m pytest tests/test_tool_metadata.py tests/test_server_functional.py tests/test_tools/test_plans.py -q
```
Only after PASS, install the branch and restart the existing tunnel/service using
`20_TRAININGPEAKS_MCP_CONNECTOR_RUNBOOK`. Refresh app tools in ChatGPT. No
reinstallation of Python, no new API keys, and no changes to athlete calendars.
Then run the existing plan reader and check its diagnostic.

## Second gate: provider deletion-route proof, disposable plan only

1. Prepare a truly disposable, private and unpriced 1-week `[MCP TEST]` plan,
   separate from plan `684463` and Beginner `679801`.
2. Add one unimportant `Other` placeholder to the disposable plan only.
3. In a TrainingPeaks web browser Network inspector (Preserve log enabled),
   DELETE just that disposable workout from the loaded plan via the UI.
4. Record **only** method, request path, HTTP response status, the deleted
   workout's provider ID, and GET readback proving the exact item is gone.
   **Never export or paste Authorization headers, cookies, access tokens,
   full HAR files or entire account data into chat or GitHub.**
5. Confirm the exact successful route matches the separately researched path
   and that its `workoutId` is the same kind of ID returned by the plan reader.
6. Only then review and set `_VERIFIED_PLAN_WORKOUT_DELETE_TEMPLATE` in code,
   test on the disposable plan, run regression tests, reinstall/refresh MCP.

## Third gate: the six approved old Other cards

On private plan 684463 alone: preflight exact plan identity, private/unpriced
status, 2027-01-04 start, one-minute Other metadata, unique provider workout ID,
existing byte-identical native note, 13 actual training sessions, 8 native notes.
Delete **one** old Other card, then read back all remaining workouts and native
notes and assert the start date. On ambiguous response, STOP; never blindly retry.
Process W2/W3/W4 and W1 phase/README first, W1 Monday anchor last. Stop and
investigate if Monday anchor or any remaining content changes.
Only when six Other cards are actually absent and full QA PASS can the migration
be marked complete.

Canonical workstream state:
Google Drive `21_TRAININGPEAKS_MCP_INTEGRATION_STATE`.
