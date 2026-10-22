"""Offline safety tests. NEVER connect to the live TrainingPeaks provider."""
from __future__ import annotations

import subprocess

import pytest
from tp_mcp.tools import ironman_operator as op


def _setup(monkeypatch, tmp_path, mode="READ_ONLY"):
    job = "native_strength_library_audit"
    script = "scripts/ironman_jobs/native_strength_library_audit.py"
    test = "tests/test_ironman_operator.py"
    (tmp_path / "scripts/ironman_jobs").mkdir(parents=True)
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / script).write_text("print('ok')\n")
    (tmp_path / test).write_text("def test_ok(): pass\n")
    (tmp_path / "python").write_text("")
    monkeypatch.setattr(op, "REPO", tmp_path)
    monkeypatch.setattr(op, "VENV_PYTHON", tmp_path / "python")
    monkeypatch.setattr(op, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(op, "_registry", lambda: {job: {
        "name": job, "mode": mode, "owner_id": op.OWNER,
        "scope": "trainingpeaks:library:3891875:read",
        "script": script, "test": test,
    }})
    return job



def test_registered_as_explicit_non_idempotent_tool():
    from tp_mcp.server import TOOLS, _TOOL_HANDLERS
    tools = [x for x in TOOLS if x.name == "tp_ironman_operator"]
    assert len(tools) == 1
    assert "job" in tools[0].input_schema["required"]
    assert "revision" in tools[0].input_schema["required"]
    assert tools[0].annotations.idempotent_hint is False
    assert "tp_ironman_operator" in _TOOL_HANDLERS


def test_rejects_secret_environment_in_child(monkeypatch, tmp_path):
    job = _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("CONTROL_PLANE_API_KEY", "must-not-leak")
    monkeypatch.setenv("PUBLIC_TEST_SETTING", "must-not-leak")
    seen = {}

    def fake_run(args, **kwargs):
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(op.subprocess, "run", fake_run)
    result = op._run("git", "status", "--porcelain")
    assert result.returncode == 0
    assert "CONTROL_PLANE_API_KEY" not in seen["env"]
    assert "PUBLIC_TEST_SETTING" not in seen["env"]
    assert seen["env"]["PYTHONPATH"].endswith("/src")


def test_operator_registry_allows_only_approved_scripts(monkeypatch, tmp_path):
    job = _setup(monkeypatch, tmp_path)
    assert op._check_job(job, "execute", None)["mode"] == "READ_ONLY"
    with pytest.raises(op.BridgeStop, match="not approved"):
        op._check_job("random_shell_script", "execute", None)


def test_operator_blocks_traversal(monkeypatch, tmp_path):
    job = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(op, "_registry", lambda: {job: {
        "name": job, "mode": "READ_ONLY", "owner_id": op.OWNER,
        "scope": "trainingpeaks:library:3891875:read",
        "script": "scripts/ironman_jobs/../../private.py",
        "test": "tests/test_ironman_operator.py",
    }})
    with pytest.raises(op.BridgeStop, match="Unsafe"):
        op._check_job(job, "execute", None)


def test_write_requires_exact_scope_acknowledgement(monkeypatch, tmp_path):
    job = _setup(monkeypatch, tmp_path, mode="GUARDED_WRITE")
    with pytest.raises(op.BridgeStop, match="scope acknowledgement"):
        op._check_job(job, "execute", None)
    with pytest.raises(op.BridgeStop, match="scope acknowledgement"):
        op._check_job(job, "execute", "wrong")
    assert op._check_job(
        job, "execute", "trainingpeaks:library:3891875:read"
    )["mode"] == "GUARDED_WRITE"


def test_requires_exact_branch_tip_before_checkout(monkeypatch, tmp_path):
    job = _setup(monkeypatch, tmp_path)
    revision = "a" * 40
    calls = []

    def fake(*args, timeout=30):
        calls.append(args)
        if args[:3] == ("git", "remote", "get-url"):
            return subprocess.CompletedProcess(args, 0, "https://github.com/Publimage/trainingpeaks-mcp.git\n", "")
        if args[:2] == ("git", "status"):
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:3] == ("git", "rev-parse", "FETCH_HEAD"):
            return subprocess.CompletedProcess(args, 0, "b" * 40 + "\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(op, "_run", fake)
    with pytest.raises(op.BridgeStop, match="differs"):
        op._execute_blocking(job, revision, "execute", None)
    assert not any(args[:3] == ("git", "checkout", "--detach") for args in calls)


def test_execute_without_any_shell_injection(monkeypatch, tmp_path):
    job = _setup(monkeypatch, tmp_path)
    revision = "a" * 40
    calls = []

    def fake(*args, timeout=30):
        calls.append(args)
        if args[:3] == ("git", "remote", "get-url"):
            value = "https://github.com/Publimage/trainingpeaks-mcp.git\n"
        elif args[:3] == ("git", "rev-parse", "FETCH_HEAD"):
            value = revision + "\n"
        elif args[0] == str(tmp_path / "python") and args[1].endswith(".py"):
            value = "MANIFEST: 19/19\nSCRITTURE_PROVIDER: 0\n"
        else:
            value = ""
        return subprocess.CompletedProcess(args, 0, value, "")

    monkeypatch.setattr(op, "_run", fake)
    result = op._execute_blocking(job, revision, "execute", None)
    assert result["success"] is True
    assert "SCRITTURE_PROVIDER: 0" in result["output"]
    assert all(isinstance(a, str) for call in calls for a in call)
    assert any(call[:3] == ("git", "checkout", "--detach") for call in calls)


def test_busy_operator_has_actionable_error_code(monkeypatch, tmp_path):
    job = _setup(monkeypatch, tmp_path)
    def busy(*args, **kwargs):
        raise BlockingIOError("another process holds the lock")
    monkeypatch.setattr(op.fcntl, "flock", busy)
    with pytest.raises(op.BridgeStop, match="Another IRONMAN job") as caught:
        op._execute_blocking(job, "a" * 40, "execute", None)
    assert caught.value.code == "OPERATOR_BUSY"


def test_revision_drift_reports_revisions_and_never_checkouts(monkeypatch, tmp_path):
    job = _setup(monkeypatch, tmp_path)
    revisions = []
    def fake(*args, timeout=30):
        revisions.append(args)
        if args[:3] == ("git", "remote", "get-url"):
            value = "https://github.com/Publimage/trainingpeaks-mcp.git\n"
        elif args[:3] == ("git", "rev-parse", "FETCH_HEAD"):
            value = "b" * 40 + "\n"
        else:
            value = ""
        return subprocess.CompletedProcess(args, 0, value, "")
    monkeypatch.setattr(op, "_run", fake)
    with pytest.raises(op.BridgeStop, match="Pinned revision differs") as caught:
        op._execute_blocking(job, "a" * 40, "execute", None)
    assert caught.value.code == "REVISION_DRIFT"
    assert "requested=aaaaaaaaaaaa" in str(caught.value)
    assert "current=bbbbbbbbbbbb" in str(caught.value)
    assert not any(x[:3] == ("git", "checkout", "--detach") for x in revisions)


def test_failed_registered_job_has_failure_code_without_retry(monkeypatch, tmp_path):
    job = _setup(monkeypatch, tmp_path)
    revision = "a" * 40
    def fake(*args, timeout=30):
        if args[:3] == ("git", "remote", "get-url"):
            return subprocess.CompletedProcess(args, 0, "https://github.com/Publimage/trainingpeaks-mcp.git\n", "")
        if args[:3] == ("git", "rev-parse", "FETCH_HEAD"):
            return subprocess.CompletedProcess(args, 0, revision + "\n", "")
        if args[0] == str(tmp_path / "python") and args[1].endswith(".py"):
            return subprocess.CompletedProcess(args, 2, '{"stage":"SAFE_STOP"}', "")
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(op, "_run", fake)
    result = op._execute_blocking(job, revision, "execute", None)
    assert result["stage"] == "STOP_REVIEW"
    assert result["error_code"] == "JOB_SCRIPT_FAILED"
    assert result["never_retry_ambiguous_post"] is False
