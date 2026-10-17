"""Offline acceptance for partial checkpoint recovery on simulated backend."""
from pathlib import Path
import tempfile
import sys
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "ironman_jobs"
sys.path.insert(0, str(SCRIPTS))
from ironman_state_store_v1 import DB_PATH
from ledger_partial_resume_canary_20261015 import (
    PREFIX, lab_paths, register, external_create, resume, state,
    run_canary, EXPECTED,
)


def test_real_process_crash_resume_and_idempotent_replay():
    r = run_canary()
    assert r["stage"] == "DO_LEDGER_PARTIAL_RESUME_ISOLATED_PASS"
    assert r["child_exit"] == -9
    assert r["first_resume"]["skipped_verified"] == 2
    assert r["first_resume"]["reconciled_uncertain"] == 1
    assert r["first_resume"]["new_simulated_writes"] == 1
    assert r["replay"]["new_simulated_writes"] == 0
    assert r["provider_writes"] == 0
    assert not r["production_ledger_access"]


def test_mismatched_remote_readback_fails_closed():
    with tempfile.TemporaryDirectory(prefix=PREFIX) as td:
        register(td)
        external_create(td, 93001, evidence="unexpected-content")
        with pytest.raises(RuntimeError, match="PROVIDER_FINGERPRINT_MISMATCH"):
            resume(td)
        assert all(s == "PENDING" for s in state(td)["items"].values())


def test_running_unknown_remote_state_blocks_retry():
    # A provider operation was marked RUNNING, but no matching remote data exists.
    with tempfile.TemporaryDirectory(prefix=PREFIX) as td:
        register(td)
        from ledger_partial_resume_canary_20261015 import transition
        transition(td, 93001, "RUNNING", "START")
        with pytest.raises(RuntimeError, match="RUNNING_WITHOUT_REMOTE_EVIDENCE_REQUIRES_REVIEW"):
            resume(td)
        assert state(td)["items"][93001] == "RUNNING"


def test_isolation_guards(tmp_path):
    with pytest.raises(RuntimeError):
        lab_paths(DB_PATH.parent)
    with pytest.raises(RuntimeError):
        lab_paths(tmp_path)
