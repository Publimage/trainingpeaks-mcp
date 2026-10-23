"""Prefect 3 pilot only: orchestrate the VERIFIED SQLite partial-resume lab.

Isolation boundary:
- no TPClient or TrainingPeaks network calls
- two temporary SQLite files only; no production ledger access
- no Prefect worker, scheduler or service deployed on DigitalOcean
- explicit lab opt-in required to launch this flow
- Prefect tracks flow/task execution; idempotency is still enforced by the
  existing domain ledger + external readback, NOT assumed from Prefect itself

Never reuse this pilot for a real-provider write or call it "durable production".
"""
from __future__ import annotations

import json
import os

from prefect import flow, task

from ledger_partial_resume_canary_20261015 import run_canary

LAB_FLAG = "IRONMAN_ISOLATED_PREFECT_LAB"
EXPECTED_STAGE = "DO_LEDGER_PARTIAL_RESUME_ISOLATED_PASS"


def validate_lab_result(result: dict) -> dict:
    """Pure, fail-closed QA gate. A flow is not PASS merely because it ran."""
    if not isinstance(result, dict) or result.get("stage") != EXPECTED_STAGE:
        raise RuntimeError("LAB_RESUME_STAGE_NOT_VERIFIED")
    if result.get("simulated_backend") is not True:
        raise RuntimeError("NON_SIMULATED_BACKEND_FORBIDDEN")
    if result.get("provider_writes") != 0 or result.get("production_ledger_access") is not False:
        raise RuntimeError("PRODUCTION_SCOPE_VIOLATION")
    if result.get("service_restarted") is not False or result.get("child_exit") != -9:
        raise RuntimeError("CRASH_OR_SERVICE_SCOPE_MISMATCH")
    first = result.get("first_resume") or {}
    replay = result.get("replay") or {}
    expected_first = {
        "skipped_verified": 2, "reconciled_uncertain": 1,
        "new_simulated_writes": 1, "external_effects_before": 3,
        "external_effects_after": 4, "done_items": 4,
        "job_state": "DONE_VERIFIED",
    }
    expected_replay = {
        "skipped_verified": 4, "reconciled_uncertain": 0,
        "new_simulated_writes": 0, "external_effects_before": 4,
        "external_effects_after": 4, "done_items": 4,
        "job_state": "DONE_VERIFIED",
    }
    if any(first.get(k) != v for k, v in expected_first.items()):
        raise RuntimeError("FIRST_RESUME_NOT_VERIFIED")
    if any(replay.get(k) != v for k, v in expected_replay.items()):
        raise RuntimeError("REPLAY_NOT_IDEMPOTENT")
    if first.get("ledger_events") != replay.get("ledger_events"):
        raise RuntimeError("LEDGER_EVENTS_CHANGED_ON_REPLAY")
    return {
        "stage": "PREFECT3_IRONMAN_ISOLATED_FLOW_PASS",
        "engine": "Prefect 3",
        "simulated_tasks_done": 4,
        "ambiguous_reconciled_by_readback": 1,
        "replay_new_external_effects": 0,
        "provider_writes": 0,
        "production_ledger_access": False,
        "service_restarted": False,
        "orchestrator_production_deployed": False,
    }


@task(name="run-verified-isolated-resume-lab", retries=0)
def run_lab_task() -> dict:
    return run_canary()


@task(name="qa-isolated-resume-readback", retries=0)
def qa_lab_task(outcome: dict) -> dict:
    return validate_lab_result(outcome)


@flow(name="ironman-prefect3-isolated-resume-pilot", retries=0, log_prints=False)
def isolated_prefect_pilot() -> dict:
    if os.environ.get(LAB_FLAG) != "1":
        raise RuntimeError("EXPLICIT_ISOLATED_LAB_FLAG_REQUIRED")
    return qa_lab_task(run_lab_task())


if __name__ == "__main__":
    print(json.dumps(isolated_prefect_pilot(), sort_keys=True), flush=True)
