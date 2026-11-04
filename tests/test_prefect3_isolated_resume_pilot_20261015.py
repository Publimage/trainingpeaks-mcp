"""Acceptance tests for REAL Prefect 3 (not a fake task/flow shim)."""
from pathlib import Path
import sys
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "ironman_jobs"
sys.path.insert(0, str(SCRIPTS))
from prefect3_isolated_resume_pilot_20261015 import (
    LAB_FLAG, isolated_prefect_pilot, run_lab_task, qa_lab_task,
    validate_lab_result,
)


def test_prefect_flow_runs_existing_isolated_checkpoint_recovery(monkeypatch):
    monkeypatch.setenv(LAB_FLAG, "1")
    result = isolated_prefect_pilot()
    assert result == {
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


def test_prefect_is_a_real_flow_with_two_real_tasks():
    assert hasattr(isolated_prefect_pilot, "flow_run_name")
    assert hasattr(run_lab_task, "task_key")
    assert hasattr(qa_lab_task, "task_key")


def test_qa_fails_closed_without_provider_readback():
    with pytest.raises(RuntimeError, match="LAB_RESUME_STAGE_NOT_VERIFIED"):
        validate_lab_result({"stage": "UNVERIFIED"})
    with pytest.raises(RuntimeError, match="NON_SIMULATED_BACKEND_FORBIDDEN"):
        validate_lab_result({"stage": "DO_LEDGER_PARTIAL_RESUME_ISOLATED_PASS",
                             "simulated_backend": False})


def test_qa_fails_closed_on_nonzero_provider_writes():
    with pytest.raises(RuntimeError, match="PRODUCTION_SCOPE_VIOLATION"):
        validate_lab_result({
            "stage": "DO_LEDGER_PARTIAL_RESUME_ISOLATED_PASS",
            "simulated_backend": True,
            "provider_writes": 1,
            "production_ledger_access": False,
        })


def test_missing_lab_flag_blocks_workflow(monkeypatch):
    monkeypatch.delenv(LAB_FLAG, raising=False)
    with pytest.raises(RuntimeError, match="EXPLICIT_ISOLATED_LAB_FLAG_REQUIRED"):
        isolated_prefect_pilot.fn()
