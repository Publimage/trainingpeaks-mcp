# IRONMAN Intermediate — Strength Builder mapping W1 (offline preparation)

**Status:** OFFLINE MAPPING ONLY — no TrainingPeaks writes, no calendar
changes, and **no native Strength Builder-in-Training-Plan integration claim**.
Date: 2026-10-09. Scope: private Intermediate lab plan 684463 (W1).

## Canonical source (authoritative for prescriptions)

Google Drive `IRONMAN — WORKOUT ARCHIVE MASTER` (`1ulKJfLdr3X2WK32XP7TSXbF90OIDXSmkjkWULpNTIgk`),
tab `CANONICAL_WORKOUTS`:
- `A6:AD6`: `IMINT24W-W01-WED-STRENGTH-02`, **Forza A | Base 35'**,
  2100 seconds, workout version 1.2, PUBLISHED/PASS.
- `A11:AD11`: `IMINT24W-W01-FRI-STRENGTH-03`, **Forza B | Richiamo 20'**,
  1200 seconds, workout version 1.3, PUBLISHED/PASS.
- `A19:AD19` and `A24:AD24`: W2 canonical copies of the same
  prescriptions. Do not alter their program doses to fit provider limitations.

**The text of those records remains the source of truth.**
The exercise-ID selection below is a *translation proposal*, not a training-plan change.

## Forza A — six candidate native exercise IDs

| Canonical exercise | Canonical prescription | TP baked exercise ID and name | Mapping |
|---|---|---|---|
| Squat **or Goblet Squat** | 3 x 6, RPE 6–7, recovery 90–120 s | `144` Goblet Squat | Candidate: use already-approved Goblet variant |
| Romanian Deadlift / hip hinge | 3 x 6, RPE 6–7, recovery 90–120 s | `154` Romanian Deadlift | Candidate, movement consistent |
| Split Squat | 2 x 6 **per side**, RPE 6–7, recovery 75–90 s | `158` Split Squat | Candidate, per-side sets |
| Calf Raise | 2 x 10 controlled, recovery 60 s | `553` Elevated Body Weight Calf Raise | REVIEW exact variant; do not force an elevated implementation |
| Row / rematore | 2 x 8, RPE 6–7, recovery 60–75 s | `516` DB Row | Candidate, verify dumbbell execution |
| Side Plank | 2 x 30 s **per side**, recovery 30 s | `79` Side Plank | Candidate; verify duration/per-side schema |

Warmup stays **5 min dynamic hip/ankle/thorax mobility plus 1 light set
of the first two exercises** until exactly mapped. Strength: no failure,
2–4 reps in reserve; existing fueling/instructions preserved. Do not
invent kg/lb values; the canonical set is RPE-based.

Approved athlete-facing YouTube references **from canonical description**:
- Goblet Squat: `https://www.youtube.com/watch?v=nfX7IFK9UNI`
- RDL: `https://www.youtube.com/watch?v=xgusDooVfKU`
- Split Squat: `https://www.youtube.com/watch?v=hPC8-z6QXco`
- Calf Raise: `https://www.youtube.com/watch?v=K_jsGgztcGU`
- Row: `https://www.youtube.com/watch?v=ufhQhwyrx-4`
- Side Plank: `https://www.youtube.com/watch?v=oQbYQyP7saI`

The 944-exercise catalogue under `src/tp_mcp/data/exercises.json`
has native video URLs for these IDs, **but they differ from the approved
canonical videos**. Retain approved links in instructions or per-exercise
coach notes. Do NOT silently approve native videos just because they load.

## Forza B — first-pass mapping, with two meaningful gaps

| Canonical exercise | Canonical prescription | Native mapping | Status |
|---|---|---|---|
| Step-up | 2 x 5 per side, RPE 6, rest 60 s | `165` Weighted Step Up / `876` Step Up with Knee Raise | **HOLD**: neither is a confirmed plain step-up; do not silently change the movement |
| Single-leg RDL | 2 x 5 per side, RPE 6, rest 60 s | `156` Single Leg Romanian Deadlift | Candidate |
| Push-up **or** Chest Press | 2 x 8, RPE 6–7, rest 60 s | `5366` Push Up | Candidate using approved option |
| Lat Pulldown **or** Row | 2 x 8, RPE 6–7, rest 60 s | `516` DB Row | Candidate using approved Row option; `935` Wide Grip Lat Pulldown changes grip |
| Pallof Press | 2 x 8 **per side**, rest 30–45 s | no `Pallof` match in 944-exercise snapshot | **HOLD**: use custom exercise UI or approved explicit equivalence, no improvised substitute |

Warmup: 4 min mobility/activation. Canonical fueling, recovery, technical
instructions and athlete-facing YouTube links remain in original row `O11`.
No change to prescribed dose.

## Transport/API boundary already established by code inspection

- `tp_create_strength_workout` sends `StructuredStrength` via
  `POST https://api.peakswaresb.com/rx/activity/v1/workouts/save`
  with a **calendarId taken from an athlete**, not a plan.
- `tp_add_training_plan_library_workout` posts **ordinary Workout Library**
  exerciseLibraryItemId via `/plans/v1/plans/{planId}/commands/addworkoutfromlibraryitem`.
  Cross-API compatibility with a native Strength Builder workout is **not proven**.
- Strength tool understands `Reps`, `RepsPerSide`, `Duration`, `RPE`, etc.
  It does **not** currently expose dedicated `RIR` or rest-between-sets
  controls in its input schema. Preserve RIR and recovery times verbatim
  in coach notes/instructions until live readback validates their native UI.
- Current Strength tool expects one numeric value per set: do not convert a
  canonical RPE **range** (e.g. 6–7) to a made-up fixed target.

## The only live validation still needed (when tunnel is back)

1. On a *brand-new private disposable* `[MCP TEST]` plan, produce **one**
   complete native Forza A with the approved instructions, six matched
   exercises, correct series/reps/RPE/recovery in the athlete-visible text.
2. Prove that the workout appears *as actual StructuredStrength* in
   **Training Plan Library**, not as a plain `Strength` card with a textual
   description. If the API route is different, capture only its method,
   path and non-secret shape.
3. Check native exercise video + approved canonical YouTube reference,
   block/sets, per-side duration, and transfer into athlete calendar via
   genuine native TP plan application (NOT the synthetic MCP copy).
4. Delete the disposable test plan using a proven plan-delete mechanism;
   if unavailable, label it clearly for later manual cleanup.
5. Only after PASS, design migration of populated Intermediate plan 684463:
   backup, no duplicate day/title, preserve existing 13 workout identities
   until replacement approved, and audit readback. Never test destructive
   migration on published Beginner 679801.

**Do not open a new full test framework.** The objective is one representative
Forza A translation and one clean provider readback, then reuse.
