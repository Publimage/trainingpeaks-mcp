"""One-command guarded release of Intermediate TEST workout and note TITLES.

Runs a non-destructive preflight unless --execute is passed.
The --execute mode invokes two existing scripts, sequentially:
  1. Replace 229 native plan workout copies with verified MASTER templates;
  2. Remove [MCP TEST] from 35 native Training Plan note titles.

Each child script validates plan ID, privacy, counts, and provider readback,
stops on ambiguity and does not touch athlete calendars. In the event of STOP,
do not blindly rerun: inspect the native TEST plan first.

Does NOT upload PDF binaries, reorder README, or publish a commercial plan.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = (
    ROOT / "scripts/replace_intermediate_endurance_titles.py",
    ROOT / "scripts/clean_intermediate_native_note_titles.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    options = parser.parse_args()
    for ix, script in enumerate(STEPS, start=1):
        command = [sys.executable, str(script)]
        if options.execute:
            command.append("--execute")
        print(f"STEP {ix}/{len(STEPS)}: {script.name} | "
              f"{'LIVE EXECUTION' if options.execute else 'READ-ONLY PREFLIGHT'}",
              flush=True)
        finished = subprocess.run(command, cwd=ROOT, check=False)
        if finished.returncode != 0:
            print(f"STOP at step {ix}, exit={finished.returncode}. "
                  "Inspect TrainingPeaks before any retry.", flush=True)
            return finished.returncode
    print("TITLE WORKFLOW PASS. PDF attachments and README ordering "
          "remain separate release gates.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
