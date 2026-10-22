"""Synthetic guards for one-off CSS Prefect canary; no provider/Drive access."""
import json
import os
from pathlib import Path
import stat

import pytest

from scripts.ironman_jobs import swim_css_live_run as core
from scripts.ironman_jobs.swim_css_live_run import (
    CanaryStop, PINNED_RECORD_SHA256, sha_json,
    private_regular_file, validate_manifest, store_report, validate_child_output,
)

REV = "a" * 40
TARGET = {
    "provider": "trainingpeaks", "owner_id": "12345",
    "resource_kind": "library_template", "container_id": "7890",
    "workout_id": "6543",
}


def conf():
    return {
        "schema": "IRONMAN_CSS_PREFECT_CANARY_V1",
        "revision": REV,
        "request": {
            "target": dict(TARGET),
            "document_id": "synthetic-document-id",
            "document_title": "11_AGENT_ORCHESTRATION_ROADMAP",
            "section": "css2200_pause300_after1200_v1",
            "reviewed_record_sha256": PINNED_RECORD_SHA256,
            "validator_revision": REV,
        },
    }


def test_reviewed_pin_scope_and_runtime_revision(monkeypatch):
    monkeypatch.setattr(core, "PINNED_TARGET_SHA256", sha_json(TARGET))
    assert validate_manifest(conf(), REV)["validator_revision"] == REV
    x = conf()
    x["revision"] = "b" * 40
    with pytest.raises(CanaryStop, match="RUNTIME_REVISION_MISMATCH"):
        validate_manifest(x, REV)
    x = conf()
    x["request"]["reviewed_record_sha256"] = "0" * 64
    with pytest.raises(CanaryStop, match="RECORD_NOT_REVIEWED"):
        validate_manifest(x, REV)
    x = conf()
    x["request"]["target"]["workout_id"] = "123"
    with pytest.raises(CanaryStop, match="TARGET_NOT_REVIEWED"):
        validate_manifest(x, REV)
    x = conf()
    x["request"]["section"] = "other"
    with pytest.raises(CanaryStop, match="SOURCE_SELECTOR_MISMATCH"):
        validate_manifest(x, REV)


def test_private_config_rejects_open_permissions_and_symlink(tmp_path):
    p = tmp_path / "manifest.json"
    p.write_text("{}")
    p.chmod(0o600)
    assert private_regular_file(p, os.getuid()) == b"{}"
    p.chmod(0o644)
    with pytest.raises(CanaryStop, match="PRIVATE_FILE_PERMISSIONS"):
        private_regular_file(p, os.getuid())
    p.chmod(0o600)
    p.rename(tmp_path / "actual")
    p.symlink_to(tmp_path / "actual")
    with pytest.raises(CanaryStop, match="PRIVATE_FILE_NOT_REGULAR"):
        private_regular_file(p, os.getuid())


def test_negative_workout_audit_is_completed_execution():
    record = {
        "stage": "SWIM_CSS_PREFECT_REPORT_RECORDED",
        "trainingpeaks_writes": 0,
        "source_rechecked": True,
        "template_rechecked": True,
        "audit_status": "FAIL",
        "distance_status": "PASS",
        "recovery_status": "FAIL",
    }
    assert validate_child_output(record)["audit_status"] == "FAIL"
    record["trainingpeaks_writes"] = 1
    with pytest.raises(RuntimeError, match="SWIM_CSS_CHILD_REPORT_INVALID"):
        validate_child_output(record)
    record["trainingpeaks_writes"] = 0
    record["source_rechecked"] = False
    with pytest.raises(RuntimeError, match="SWIM_CSS_CHILD_REPORT_INVALID"):
        validate_child_output(record)


def test_report_persistence_unique_and_byte_readback(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "REPORT_DIR", tmp_path)
    first, digest = store_report({"status": "FAIL"})
    assert Path(first).exists()
    assert stat.S_IMODE(Path(first).stat().st_mode) == 0o600
    assert len(digest) == 64
    assert json.loads(Path(first).read_text()) == {"status": "FAIL"}
    second, _ = store_report({"status": "FAIL"})
    assert first != second
