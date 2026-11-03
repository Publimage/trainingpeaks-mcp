"""Offline verification of independent read-only publisher status.

Import by file to keep these tests free of network and provider dependencies.
"""
import importlib.util
import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src/tp_mcp/tools/ironman_publisher_status.py"
spec = importlib.util.spec_from_file_location("inspector_under_test", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fill(tmp_path, configured=False, jobs=None):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "ironman_operator_jobs.json").write_text(json.dumps({
        "schema": "IRONMAN_OPERATOR_JOBS_V1",
        "jobs": jobs or [
            {"name": "reviewed_plan_patch_preview", "mode": "READ_ONLY",
             "owner_id": 2116886},
            {"name": "reviewed_plan_patch_publish", "mode": "GUARDED_WRITE",
             "owner_id": 2116886},
        ]
    }), encoding="utf-8")
    (data / "ironman_reviewed_plan_patch.json").write_text(json.dumps({
        "schema": "IRONMAN_REVIEWED_PLAN_PATCH_CONFIG_V1",
        "configured": configured
    }), encoding="utf-8")


def test_status_idle_is_accurate_without_mutation(tmp_path):
    fill(tmp_path, False)
    before = {p.name: p.read_bytes() for p in (tmp_path / "data").iterdir()}
    result = module.inspect_publisher(tmp_path)
    after = {p.name: p.read_bytes() for p in (tmp_path / "data").iterdir()}
    assert before == after
    assert result["stage"] == "IRONMAN_PUBLISHER_READ_ONLY_STATUS"
    assert result["jobs_registered"] == {
        "reviewed_plan_patch_preview": True,
        "reviewed_plan_patch_publish": True,
    }
    assert result["manifest_configured"] is False
    assert result["status"] == "REVIEWED_BATCH_PENDING"
    assert result["provider_writes"] == 0
    assert result["live_writer_verified"] is False


def test_status_active_is_not_write_success(tmp_path):
    fill(tmp_path, True)
    got = module.inspect_publisher(tmp_path)
    assert got["manifest_configured"] is True
    assert got["status"] == "REVIEWED_BATCH_PRESENT_UNVERIFIED"
    assert got["live_writer_verified"] is False


def test_missing_root_does_not_claim_ready(tmp_path):
    r = module.inspect_publisher(tmp_path)
    assert r["registry_readable"] is False
    assert r["manifest_readable"] is False
    assert not any(r["jobs_registered"].values())
    assert r["provider_writes"] == 0


def test_wrong_job_owner_or_mode_fails_readiness(tmp_path):
    fill(tmp_path, jobs=[{"name": "reviewed_plan_patch_preview",
                          "mode": "GUARDED_WRITE", "owner_id": 1}])
    result = module.inspect_publisher(tmp_path)
    assert not any(result["jobs_registered"].values())


def test_manifest_symlink_is_not_followed(tmp_path):
    fill(tmp_path)
    target = tmp_path / "sensitive.json"
    target.write_text('{"schema":"IRONMAN_REVIEWED_PLAN_PATCH_CONFIG_V1","configured":true}')
    manifest = tmp_path / "data/ironman_reviewed_plan_patch.json"
    manifest.unlink()
    manifest.symlink_to(target)
    result = module.inspect_publisher(tmp_path)
    assert result["manifest_readable"] is False
    assert result["manifest_configured"] is False


def test_code_has_no_shell_or_network_execution():
    source = SOURCE.read_text(encoding="utf-8")
    import ast
    parsed = ast.parse(source)
    imports = [n.module for n in ast.walk(parsed) if isinstance(n, ast.ImportFrom)]
    imports += [alias.name for n in ast.walk(parsed) if isinstance(n, ast.Import) for alias in n.names]
    assert "subprocess" not in imports
    assert "os.system" not in source
    assert "checkout" not in source.split("def inspect_publisher")[1].split("async def")[0]
    assert "asyncio.to_thread" not in source


def _load_runtime_listener_reader():
    """Load standalone listener reader without network/provider dependencies."""
    import importlib.util
    source = Path(__file__).resolve().parents[1] / "src/tp_mcp/tools/ironman_runtime_status.py"
    spec = importlib.util.spec_from_file_location("ironman_runtime_reader_ci", source)
    assert spec is not None and spec.loader is not None
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    return reader


def test_runtime_reader_ci_exact_private_bind_and_local_tunnel(tmp_path, monkeypatch):
    reader = _load_runtime_listener_reader()
    proc = tmp_path / "tcp"
    proc.write_text(
        "sl local_address rem_address st\n"
        "0: 0200720A:2253 00000000:0000 0A\n"
        "1: 0100007F:1F90 00000000:0000 0A\n"
        "2: 0500130A:2253 00000000:0000 0A\n",
        encoding="ascii",
    )
    kernel_reader = reader._listening_ipv4
    monkeypatch.setattr(reader, "_listening_ipv4", lambda: kernel_reader(proc))
    result = reader.tp_get_ironman_runtime_status()
    assert result["bridge_listener"] == "LISTENING"
    assert result["tunnel_listener"] == "LISTENING"
    assert result["provider_writes"] == 0
    assert result["evidence"] == "linux_proc_tcp_local_namespace"


def test_runtime_reader_ci_wrong_private_bind_does_not_claim_healthy(tmp_path, monkeypatch):
    reader = _load_runtime_listener_reader()
    proc = tmp_path / "tcp"
    proc.write_text(
        "sl local_address rem_address st\n0: 0500130A:2253 00000000:0000 0A\n",
        encoding="ascii",
    )
    kernel_reader = reader._listening_ipv4
    monkeypatch.setattr(reader, "_listening_ipv4", lambda: kernel_reader(proc))
    assert reader.tp_get_ironman_runtime_status()["bridge_listener"] == "NOT_OBSERVED"
    monkeypatch.setattr(reader, "_listening_ipv4", lambda: kernel_reader(tmp_path / "absent"))
    assert reader.tp_get_ironman_runtime_status()["bridge_listener"] == "UNKNOWN"


def test_runtime_reader_ci_tool_remains_separate_from_executable_operator():
    """Source contract; not a substitute for actual SDK integration tests."""
    import ast
    root = Path(__file__).resolve().parents[1]
    reader_text = (root / "src/tp_mcp/tools/ironman_runtime_status.py").read_text(encoding="utf-8")
    server_text = (root / "src/tp_mcp/server.py").read_text(encoding="utf-8")
    tree = ast.parse(reader_text)
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    modules.update(a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names)
    assert not modules.intersection({"subprocess", "requests", "httpx", "tp_mcp.client"})
    assert 'name="tp_get_ironman_runtime_status"' in server_text
    assert '@_handler("tp_get_ironman_runtime_status")' in server_text
    assert '"tp_ironman_operator",' in server_text.split('_NON_IDEMPOTENT_WRITES = {', 1)[1].split('}', 1)[0]
    assert '"tp_ironman_operator"' not in server_text.split('_READ_ONLY_EXTRA = ', 1)[1].split('\n', 1)[0]
