"""Fast isolated safety tests; the real server/worker test runs in a separate CI step."""
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts" / "ironman_jobs"
sys.path.insert(0, str(SCRIPTS))

from prefect3_worker_lifecycle_canary_20261015 import require_env, yaml_config, POOL, FLOW_ENTRYPOINT
from prefect3_worker_resume_flow_20261015 import worker_resume_flow, verify_lab_checkpoint
from ironman_state_store_v1 import DB_PATH
from ledger_partial_resume_canary_20261015 import lab_paths


def test_explicit_lab_flag_is_mandatory(monkeypatch):
    monkeypatch.delenv("IRONMAN_ISOLATED_PREFECT_LAB", raising=False)
    with pytest.raises(RuntimeError, match="EXPLICIT_ISOLATED_LAB_FLAG_REQUIRED"):
        require_env()
    with pytest.raises(RuntimeError, match="EXPLICIT_ISOLATED_LAB_FLAG_REQUIRED"):
        worker_resume_flow.fn(str(DB_PATH.parent))


def test_production_ledger_is_not_valid_lab_root():
    with pytest.raises(RuntimeError, match="ONLY_DIRECT_TEMPORARY_LAB_ROOT_ALLOWED"):
        lab_paths(DB_PATH.parent)


def test_mock_checkpoint_audit_is_fail_closed():
    with pytest.raises(RuntimeError, match="WORKER_LAB_JOB_NOT_DONE_VERIFIED"):
        verify_lab_checkpoint.fn({"job_state": "RUNNING"})
    with pytest.raises(RuntimeError, match="WORKER_LAB_UNEXPECTED_REMOTE_BASELINE"):
        verify_lab_checkpoint.fn({
            "job_state": "DONE_VERIFIED", "done_items": 4,
            "external_effects_after": 4, "external_effects_before": 9,
            "ledger_events": 10,
        })


def test_versioned_deployment_confined_to_process_lab(tmp_path):
    text = yaml_config(tmp_path).read_text()
    assert "name: resume-lab" in text
    assert f'name: "{POOL}"' in text
    assert FLOW_ENTRYPOINT in text
    assert "git_clone" not in text
    assert "docker" not in text
    assert "tp_client" not in text.lower()
    assert "http://" not in text.lower() and "https://" not in text.lower()
