"""Explicitly authorized CSS-only activation followed by the proven reload.

No caller commands, provider writes or changes to the existing reload helper.
Configuration is independently read back before any reload is scheduled.
"""
import asyncio
import importlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.ironman_jobs.swim_audit_runtime_activation import configure

if __name__ == "__main__":
    outcome = asyncio.run(configure())
    print(json.dumps(outcome, sort_keys=True), flush=True)
    # Executes the existing, pinned helper in this same child process so its
    # parent/tunnel identity guards apply unchanged. It schedules SIGTERM only.
    importlib.import_module("scripts.ironman_jobs.mcp_catalog_reload_20261016")
