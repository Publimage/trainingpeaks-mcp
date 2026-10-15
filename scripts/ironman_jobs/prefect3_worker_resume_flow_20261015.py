"""Safe staging flow, invoked ONLY from the isolated GitHub Actions worker lab.

Uses the existing verified recovery algorithm and two disposable SQLite DBs.
Not a provider adapter, production deployment, or exactly-once guarantee.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from prefect import flow, task

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ledger_partial_resume_canary_20261015 import lab_paths, resume

LAB_FLAG = "IRONMAN_ISOLATED_PREFECT_LAB"


@task(name="recover-mock-provider-checkpoints", retries=0)
def reconcile_lab_checkpoint(root: str) -> dict:
    lab_paths(Path(root))  # Mandatory strong path gate before any I/O.
    return resume(root)


@task(name="verify-mock-provider-checkpoints", retries=0)
def verify_lab_checkpoint(result: dict) -> dict:
    if result.get("job_state") != "DONE_VERIFIED":
        raise RuntimeError("WORKER_LAB_JOB_NOT_DONE_VERIFIED")
    if result.get("done_items") != 4 or result.get("external_effects_after") != 4:
        raise RuntimeError("WORKER_LAB_ITEM_COUNT_MISMATCH")
    if result.get("external_effects_before") not in (3, 4):
        raise RuntimeError("WORKER_LAB_UNEXPECTED_REMOTE_BASELINE")
    if result.get("ledger_events") != 10:
        raise RuntimeError("WORKER_LAB_EVENT_COUNT_DRIFT")
    if result.get("external_effects_before") == 3 and (
        result.get("new_simulated_writes") != 1
        or result.get("reconciled_uncertain") != 1
        or result.get("skipped_verified") != 2
    ):
        raise RuntimeError("WORKER_LAB_UNSAFE_FIRST_RESUME")
    if result.get("external_effects_before") == 4 and (
        result.get("new_simulated_writes") != 0
        or result.get("reconciled_uncertain") != 0
        or result.get("skipped_verified") != 4
    ):
        raise RuntimeError("WORKER_LAB_UNSAFE_REPLAY")
    return {
        "stage": "PREFECT3_WORKER_LAB_VERIFIED",
        "mock_effects": 4,
        "ledger_events": 10,
        "new_mock_effects": result["new_simulated_writes"],
        "trainingpeaks_writes": 0,
        "production_ledger_access": False,
    }


@flow(name="ironman-prefect3-worker-restart-lab", retries=0, log_prints=False)
def worker_resume_flow(root: str) -> dict:
    if os.environ.get(LAB_FLAG) != "1":
        raise RuntimeError("EXPLICIT_ISOLATED_LAB_FLAG_REQUIRED")
    lab_paths(Path(root))
    return verify_lab_checkpoint(reconcile_lab_checkpoint(root))
