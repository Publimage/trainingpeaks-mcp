# IRONMAN field edits — GitHub workflow

Use the existing source-controlled connector: GitHub -> `git pull` in `~/trainingpeaks-mcp`. Do not distribute scripts through ZIP for routine development.

Current safety gate: select and preview edits by UID, sport, week, field and locale; do not write to TrainingPeaks until the direct plan-workout PUT has passed a disposable-plan canary with native ID/structure/readback and restoration. TrainingPeaks plan 684602 and athlete calendars are excluded from experimental write testing. Source of truth remains the Google Drive IRONMAN Knowledge Base.

The legacy 229 plan workout IDs in `data/intermediate_plan_title_release_manifest.json` are all stale after renaming. Before any future write, rebind identities from live TrainingPeaks reads and fail on ambiguity. Notes and workouts must not be confused with one-minute Other templates.
