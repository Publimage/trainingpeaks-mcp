from pathlib import Path
import json

from scripts.ironman_jobs.prefect_admin_pull_agent import validate_manifest


def test_manifest_status_is_allowlisted():
    data = {
        "schema": "IRONMAN_PREFECT_ADMIN_COMMAND_V1",
        "job_id": "bootstrap-status-20261016-001",
        "operation": "status",
        "params": {},
    }
    out = validate_manifest(data)
    assert out["operation"] == "status"


def test_manifest_rejects_arbitrary_operation():
    data = {
        "schema": "IRONMAN_PREFECT_ADMIN_COMMAND_V1",
        "job_id": "bad-command-20261016-001",
        "operation": "shell",
        "params": {"command": "id"},
    }
    try:
        validate_manifest(data)
    except RuntimeError as exc:
        assert "OPERATION_NOT_ALLOWED" in str(exc)
    else:
        raise AssertionError("arbitrary operation accepted")


def test_installer_has_no_public_listener():
    text = Path("scripts/ironman_jobs/install_prefect_admin_pull_agent_20261016.sh").read_text()
    assert "systemd" in text
    assert "OnUnitActiveSec=30s" in text
    assert "ListenStream" not in text
    assert "0.0.0.0" not in text
