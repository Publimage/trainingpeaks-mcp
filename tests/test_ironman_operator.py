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


def test_reviewed_plan_jobs_require_independent_plan_id_before_checkout(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    revision = "a" * 40
    with pytest.raises(op.BridgeStop, match="TARGET_PLAN_ID_REQUIRED"):
        op._execute_blocking("reviewed_plan_patch_publish", revision, "execute", None)
    with pytest.raises(op.BridgeStop, match="TARGET_PLAN_ID_REQUIRED"):
        op._execute_blocking("reviewed_plan_patch_preview", revision, "execute", None)
    with pytest.raises(op.BridgeStop, match="TARGET_PLAN_ID_REQUIRED"):
        op._execute_blocking("reviewed_plan_patch_publish", revision, "execute", None, True)
    with pytest.raises(op.BridgeStop, match="TARGET_PLAN_ID_REQUIRED"):
        op._execute_blocking("reviewed_plan_patch_publish", revision, "execute", None, -1)


def test_plan_id_is_the_only_extra_environment_variable(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("UNTRUSTED_TARGET", "684602")
    captured = {}
    def fake_run(args, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(op.subprocess, "run", fake_run)
    op._run("python", "a.py", request_plan_id=689369)
    assert captured["env"]["IRONMAN_REQUEST_TARGET_PLAN_ID"] == "689369"
    assert "UNTRUSTED_TARGET" not in captured["env"]


def test_operator_schema_declares_live_verified_target_plan_id():
    from tp_mcp.server import TOOLS
    tool = next(t for t in TOOLS if t.name == "tp_ironman_operator")
    assert tool.input_schema["properties"]["target_plan_id"]["type"] == "integer"
    assert tool.input_schema["properties"]["target_plan_id"]["minimum"] == 1


def test_reviewed_manifest_mismatch_stops_before_any_provider_job(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    (tmp_path / "data").mkdir()
    manifest = tmp_path / "data/ironman_reviewed_plan_patch.json"
    manifest.write_text('{"configured":true,"manifest":{"plan_id":684602}}')
    with pytest.raises(op.BridgeStop, match="STOP_TARGET_MISMATCH"):
        op._check_reviewed_manifest_target("reviewed_plan_patch_publish", 689369)
    with pytest.raises(op.BridgeStop, match="STOP_TARGET_MISMATCH"):
        op._check_reviewed_manifest_target("reviewed_plan_patch_preview", 689369)
    op._check_reviewed_manifest_target("reviewed_plan_patch_preview", 684602)
    op._check_reviewed_manifest_target("reviewed_plan_patch_publish", 684602)


def test_reviewed_manifest_inactive_must_not_publish(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    (tmp_path / "data").mkdir()
    manifest = tmp_path / "data/ironman_reviewed_plan_patch.json"
    manifest.write_text('{"configured":false}')
    op._check_reviewed_manifest_target("reviewed_plan_patch_preview", 689369)
    with pytest.raises(op.BridgeStop, match="REVIEWED_MANIFEST_NOT_ACTIVE"):
        op._check_reviewed_manifest_target("reviewed_plan_patch_publish", 689369)
