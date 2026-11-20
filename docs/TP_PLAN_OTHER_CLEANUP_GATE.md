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


## Local disposable probe — staged 2026-10-09

The verified native reader after the coach's 107-passed local regression suite
returned the complete six-card diagnostic in plan 684463: all six unique
provider `workoutId` values were available, each one was a 1-minute Other,
and all six had a byte-identical native-note counterpart. The plan still
contained 13 true workouts, 6 legacy Other cards, and 8 native notes.
This is a READ-ONLY audit; it does not validate the actual deletion route.

The repo now includes `scripts/probe_training_plan_delete.py`, a separate
local script that **never deletes from plan 684463 or any athlete**. It uses
one private, one-week sacrificial `[MCP TEST]` plan anchored Monday
2027-07-05 and three copies of the approved Other library template 14940092.
It adds one Monday native note and attempts exactly two one-shot deletions:
1. Wednesday (non-anchor) to validate the actual plan-scoped route and GET
   readback of the two surviving cards, unchanged Monday start and native note;
2. Monday's original seed (with a Tuesday Other + Monday note surviving) to
   measure whether TrainingPeaks shifts the plan start date. A shifted anchor
   MUST BLOCK deleting the Monday seed from actual Intermediate 684463.

The script checks private/unpriced identity, hardcoded disposable title,
provider ID uniqueness and Other metadata. It disables automatic retry on
401 for its DELETE requests, refuses a reused disposable title, stops on
ambiguous writes, and prints no credentials. It leaves one disposable
Tuesday Other behind for audit.

Five mock-only tests were added under
`tests/test_probe_training_plan_delete.py`.
These were created **after** the coach's reported 107-passed run and MUST be
executed locally before invoking `--execute`.

On Mac (existing .venv; NO tunnel restart required for this standalone script):
```bash
cd ~/trainingpeaks-mcp
git pull --ff-only
source .venv/bin/activate
python -m pytest tests/test_probe_training_plan_delete.py -q
python scripts/probe_training_plan_delete.py
```
If and ONLY IF new tests + read-only preflight are green, run:
```bash
python scripts/probe_training_plan_delete.py --execute
```
Copy only the sanitized JSON result, not browser HAR, tokens or logs.
If any step fails/returns STOP, do NOT repeat automatically.

After independent live proof and anchor-preservation result, the cleanup tool
may be enabled/retested before deleting the six real-plan legacy cards.


## 2026-10-09 observed live disposable proof and streamlined production cleanup

TrainingPeaks live readback after the coach's disposable test:
- Disposable private Plan `684484` exists with exactly **one surviving Tuesday
  Other** workout, provider workout ID `3995256662`.
- Its **native Monday note** (`2651317`) survived, and the plan start date
  remained **2027-07-05** after removing the original Monday Other.
- The two staged DELETE calls therefore produced the anticipated observable
  final state. The coach ran the local probe; full Terminal output was not
  captured. The disposable plan still exists: deleting the entire plan has
  **not** been implemented/confirmed.
- Intermediate pilot `684463` remains unchanged: 13 workouts, 6 old Other
  cards, 8 native notes.

For the protected Intermediate pilot, a **single-purpose runner** was added:
`scripts/cleanup_intermediate_other.py --execute`. It uses the existing
`tp_delete_training_plan_other` six-item allowlist and live readback, with
provider identities checked against the six known workout IDs and matching
native note IDs. The verified endpoint is enabled only in that one-shot local
process: the MCP server remains fail-closed by default. The runner always
keeps W1's Monday anchor deletion last and stops immediately on any mismatch.
The native notes reader and workouts reader use a fixed 24-week pilot read
window so deletion-induced shrinking `dayCount` does not hide W3/W4 notes.

Local gate (in Mac venv; tunnel does not require a restart):
```bash
cd ~/trainingpeaks-mcp
git pull --ff-only
source .venv/bin/activate
python -m pytest tests/test_tools/test_plans.py -q && python scripts/cleanup_intermediate_other.py --execute
```
Do not repeat the execute command after ambiguous errors; inspect the live
pilot plan first.

**Simplified experimental standard from the coach:** create a brand-new unused,
private, disposable `[MCP TEST]` plan, test the one feature, check result,
then delete the whole test plan once a verified deletion method is available.
A populated, completed or public commercial plan stays in a protected workflow
with scope checks, readback, and conservation of its existing content. No
general test plan needs a 24-week product-level safety process.
