"""Local-only activation/review tests with synthetic target identities."""
import ast
import json
import os
from pathlib import Path
from typing import Any
import pytest
from scripts.ironman_jobs import swim_audit_runtime_activation as module

TARGET = {"provider": "trainingpeaks", "owner_id": "200", "resource_kind": "library_template",
          "container_id": "300", "workout_id": "400"}


def configured(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "TARGET_PIN", module.digest(TARGET))
    path = tmp_path / "bridge.json"
    original = {"host": "10.114.0.2", "port": 8787,
                "allowed_sources": ["10.114.0.2", "10.114.0.3"],
                "allowed_athletes": ["900"], "result_writer_sources": ["10.114.0.3"],
                "max_window_days": 21, "unrelated_setting": {"preserve": True}}
    path.write_text(json.dumps(original))
    path.chmod(0o600)
    return path, original


def test_config_changes_only_one_field_with_private_exact_backup(tmp_path, monkeypatch):
    path, original = configured(tmp_path, monkeypatch)
    before = path.read_bytes()
    result = module.enable_sample(path, TARGET)
    after = json.loads(path.read_bytes())
    assert result["changed"] is True
    assert after.pop("allowed_swim_templates") == [TARGET]
    assert after == original
    copies = list((tmp_path / "swim-audit-backups").glob("*.json"))
    assert len(copies) == 1 and copies[0].read_bytes() == before
    assert copies[0].stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o777 == 0o600


def test_config_idempotent_no_second_backup(tmp_path, monkeypatch):
    path, _ = configured(tmp_path, monkeypatch)
    module.enable_sample(path, TARGET)
    before = path.read_bytes()
    assert module.enable_sample(path, TARGET)["changed"] is False
    assert path.read_bytes() == before
    assert len(list((tmp_path / "swim-audit-backups").glob("*.json"))) == 1


def test_wrong_target_never_writes(tmp_path, monkeypatch):
    path, _ = configured(tmp_path, monkeypatch)
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="TARGET_NOT_APPROVED"):
        module.enable_sample(path, dict(TARGET, workout_id="401"))
    assert path.read_bytes() == before and not (tmp_path / "swim-audit-backups").exists()


def test_other_allowlist_not_overwritten(tmp_path, monkeypatch):
    path, original = configured(tmp_path, monkeypatch)
    original["allowed_swim_templates"] = [dict(TARGET, workout_id="401")]
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="OTHER_SWIM_TARGETS_PRESENT"):
        module.enable_sample(path, TARGET)
    assert path.read_bytes() == before


@pytest.mark.parametrize("key,value", [("host", "0.0.0.0"), ("port", 8788), ("allowed_sources", [])])
def test_wrong_configuration_never_writes(tmp_path, monkeypatch, key, value):
    path, original = configured(tmp_path, monkeypatch)
    original[key] = value
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    with pytest.raises(RuntimeError):
        module.enable_sample(path, TARGET)
    assert path.read_bytes() == before


def test_symlink_config_rejected(tmp_path, monkeypatch):
    path, _ = configured(tmp_path, monkeypatch)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(RuntimeError, match="CONFIG_PATH_NOT_REGULAR"):
        module.enable_sample(link, TARGET)


def test_wrong_host_rejected(monkeypatch):
    monkeypatch.setattr(module.socket, "gethostname", lambda: "other-host")
    with pytest.raises(RuntimeError, match="WRONG_HOST"):
        module.require_host()


def registry_function(tmp_path):
    # Compile the actual small parser, without importing authenticated clients.
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/tp_mcp/tools/ironman_operator.py").read_text()
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                    and n.name == "_registry")
    ns = {"REPO": tmp_path, "REGISTRY_PATH": Path("data/ironman_operator_jobs.json"),
          "OWNER": 200, "BridgeStop": RuntimeError, "Any": Any, "json": json}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "actual-registry", "exec"), ns)
    return ns["_registry"]


def registry_files(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir()
    (directory / "ironman_operator_jobs.json").write_text(json.dumps({
        "schema": "IRONMAN_OPERATOR_JOBS_V1", "owner": 200, "jobs": [{"name": "old_job"}]}))
    return directory / "ironman_swim_operator_jobs.json"


def test_optional_registry_absent_preserves_existing_jobs(tmp_path):
    registry_files(tmp_path)
    assert registry_function(tmp_path)() == {"old_job": {"name": "old_job"}}


def test_fixed_extension_keeps_original_entries(tmp_path):
    extension = registry_files(tmp_path)
    extension.write_text(json.dumps({"schema": "IRONMAN_OPERATOR_JOBS_V1", "owner": 200,
                                     "jobs": [{"name": "swim_job"}]}))
    assert set(registry_function(tmp_path)()) == {"old_job", "swim_job"}


def test_extension_cannot_replace_registered_job(tmp_path):
    extension = registry_files(tmp_path)
    extension.write_text(json.dumps({"schema": "IRONMAN_OPERATOR_JOBS_V1", "owner": 200,
                                     "jobs": [{"name": "old_job"}]}))
    with pytest.raises(RuntimeError, match="Duplicate job"):
        registry_function(tmp_path)()


@pytest.mark.parametrize("bad", [{"schema": "wrong", "owner": 200, "jobs": []},
                                 {"schema": "IRONMAN_OPERATOR_JOBS_V1", "owner": 201, "jobs": []},
                                 {"schema": "IRONMAN_OPERATOR_JOBS_V1", "owner": 200, "jobs": {}}])
def test_registry_extension_fails_closed(tmp_path, bad):
    extension = registry_files(tmp_path)
    extension.write_text(json.dumps(bad))
    with pytest.raises(RuntimeError, match="Unapproved swim"):
        registry_function(tmp_path)()
