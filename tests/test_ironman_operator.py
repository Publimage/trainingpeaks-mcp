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
    assert tool.input_schema["properties"]["request_scope"]["type"] == "string"
    assert tool.input_schema["properties"]["requested_workout_ids"]["uniqueItems"] is True
    assert tool.input_schema["properties"]["requested_workout_ids"]["maxItems"] == 150


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
    op._check_reviewed_manifest_request("reviewed_plan_patch_preview", None, None)
    with pytest.raises(op.BridgeStop, match="REVIEWED_MANIFEST_NOT_ACTIVE"):
        op._check_reviewed_manifest_target("reviewed_plan_patch_publish", 689369)


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



def test_stale_same_plan_manifest_cannot_select_a_new_request(monkeypatch, tmp_path):
    """Plan ID alone cannot distinguish two edits of WINTER FOUNDATION."""
    _setup(monkeypatch, tmp_path)
    (tmp_path / "data").mkdir()
    prior_scope = "trainingpeaks:plan:689369:winter8-batch-already-completed"
    payload = {"configured": True, "manifest": {
        "plan_id": 689369, "scope": prior_scope,
        "items": [{"workout_id": 36271815}, {"workout_id": 36271819}],
    }}
    (tmp_path / "data/ironman_reviewed_plan_patch.json").write_text(
        __import__("json").dumps(payload))

    op._check_reviewed_manifest_target("reviewed_plan_patch_preview", 689369)
    op._check_reviewed_manifest_request(
        "reviewed_plan_patch_preview", prior_scope, [36271815, 36271819])
    # Same plan, different request: stop before the provider or a write receipt.
    with pytest.raises(op.BridgeStop, match="STOP_REQUEST_SCOPE_MISMATCH"):
        op._check_reviewed_manifest_request(
            "reviewed_plan_patch_publish",
            "trainingpeaks:plan:689369:new-single-description",
            [36271815, 36271819])
    with pytest.raises(op.BridgeStop, match="STOP_REQUEST_RESOURCE_MISMATCH"):
        op._check_reviewed_manifest_request(
            "reviewed_plan_patch_publish", prior_scope, [36271815])
    with pytest.raises(op.BridgeStop, match="REQUEST_SCOPE_REQUIRED"):
        op._check_reviewed_manifest_request(
            "reviewed_plan_patch_publish", None, [36271815, 36271819])
    with pytest.raises(op.BridgeStop, match="REQUEST_WORKOUT_IDS_REQUIRED"):
        op._check_reviewed_manifest_request(
            "reviewed_plan_patch_publish", prior_scope, [36271815, 36271815])
    with pytest.raises(op.BridgeStop, match="REQUEST_WORKOUT_IDS_REQUIRED"):
        op._check_reviewed_manifest_request(
            "reviewed_plan_patch_publish", prior_scope, [True, 36271819])


def test_reviewed_job_passes_only_verified_request_identity_to_child(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    captured = {}

    def fake_run(args, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(op.subprocess, "run", fake_run)
    scope = "trainingpeaks:plan:689369:another-request"
    op._run("python", "approved.py", request_plan_id=689369,
            request_scope=scope, request_workout_ids=[13, 11])
    assert captured["env"]["IRONMAN_REQUEST_TARGET_PLAN_ID"] == "689369"
    assert captured["env"]["IRONMAN_REQUEST_TARGET_SCOPE"] == scope
    assert captured["env"]["IRONMAN_REQUEST_WORKOUT_IDS_JSON"] == "[11,13]"
    assert not any("PASSWORD" in k or "TOKEN" in k for k in captured["env"])



def test_operator_stdout_never_returns_provider_credentials(monkeypatch, tmp_path):
    job = _setup(monkeypatch, tmp_path)
    revision = "a" * 40

    def fake(*args, timeout=30):
        if args[:3] == ("git", "remote", "get-url"):
            value = "https://github.com/Publimage/trainingpeaks-mcp.git\n"
        elif args[:3] == ("git", "rev-parse", "FETCH_HEAD"):
            value = revision + "\n"
        elif args[0] == str(tmp_path / "python") and args[1].endswith(".py"):
            value = (
                "Authorization: Bearer DEMO_OPERATOR_AUTH\n"
                "Cookie: session=DEMO_OPERATOR_COOKIE; mode=secret\n"
                "token=DEMO_OPERATOR_TOKEN\n"
                "SAFE_STATUS: PASS\n"
            )
        else:
            value = ""
        return subprocess.CompletedProcess(args, 0, value, "")

    monkeypatch.setattr(op, "_run", fake)
    result = op._execute_blocking(job, revision, "execute", None)
    assert result["success"] is True
    assert result["stage"] == "DONE"
    for token in ("DEMO_OPERATOR_AUTH", "DEMO_OPERATOR_COOKIE",
                  "DEMO_OPERATOR_TOKEN"):
        assert token not in result["output"]
    assert "SAFE_STATUS: PASS" in result["output"]



def test_shared_dynamic_target_resolver_is_registered_read_only():
    from tp_mcp.server import TOOLS, _TOOL_HANDLERS

    found = [t for t in TOOLS if t.name == "tp_ironman_resolve_target"]
    assert len(found) == 1
    tool = found[0]
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert "tp_ironman_resolve_target" in _TOOL_HANDLERS
    assert tool.input_schema["required"] == ["kind", "query"]
    assert "new_training_plan" in tool.input_schema["properties"]["kind"]["enum"]
    assert "athlete_workout" in tool.input_schema["properties"]["kind"]["enum"]
    assert "plan_note" in tool.input_schema["properties"]["kind"]["enum"]
