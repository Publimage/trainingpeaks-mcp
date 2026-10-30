"""Behavior and metadata contract of the no-side-effects diagnostic tool."""
from pathlib import Path
import importlib.util

MODULE_PATH = Path(__file__).resolve().parents[1] / "src/tp_mcp/tools/ironman_runtime_status.py"
SPEC = importlib.util.spec_from_file_location("ironman_runtime_status_unit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)


def test_listener_inventory_reports_only_selected_local_services(tmp_path: Path, monkeypatch):
    fixture = tmp_path / "tcp"
    fixture.write_text(
        "sl local_address rem_address st\n"
        "0: 0200720A:2253 00000000:0000 0A\n"  # 10.114.0.2:8787
        "1: 0100007F:1F90 00000000:0000 0A\n"  # 127.0.0.1:8080
        "2: 0100007F:2328 00000000:0000 01\n"  # ESTABLISHED: ignored
        "3: 0100007F:0016 00000000:0000 0A\n", # unrelated SSH
        encoding="ascii",
    )
    original = status._listening_ipv4
    monkeypatch.setattr(status, "_listening_ipv4", lambda: original(fixture))
    out = status.tp_get_ironman_runtime_status()
    assert out == {
        "schema": "IRONMAN_RUNTIME_LISTENERS_V1",
        "bridge_listener": "LISTENING",
        "tunnel_listener": "LISTENING",
        "evidence": "linux_proc_tcp_local_namespace",
        "provider_writes": 0,
    }
    assert original(fixture) == {
        ("10.114.0.2", 8787), ("127.0.0.1", 8080), ("127.0.0.1", 22)
    }


def test_missing_proc_does_not_claim_bridge_down(tmp_path: Path, monkeypatch):
    original = status._listening_ipv4
    monkeypatch.setattr(status, "_listening_ipv4", lambda: original(tmp_path / "absent"))
    out = status.tp_get_ironman_runtime_status()
    assert out["bridge_listener"] == "UNKNOWN"
    assert out["tunnel_listener"] == "UNKNOWN"
    assert out["provider_writes"] == 0


def test_unrelated_listener_is_not_proof_of_bridge(tmp_path: Path, monkeypatch):
    fixture = tmp_path / "tcp"
    fixture.write_text("sl local_address rem_address st\n0: 0100007F:2253 00000000:0000 0A\n", encoding="ascii")
    original = status._listening_ipv4
    monkeypatch.setattr(status, "_listening_ipv4", lambda: original(fixture))
    out = status.tp_get_ironman_runtime_status()
    assert out["bridge_listener"] == "NOT_OBSERVED"
    assert out["tunnel_listener"] == "NOT_OBSERVED"


def test_catalog_keeps_write_capable_operator_non_readonly():
    from tp_mcp.server import TOOLS, _TOOL_HANDLERS
    status_tool = next(t for t in TOOLS if t.name == "tp_get_ironman_runtime_status")
    operator_tool = next(t for t in TOOLS if t.name == "tp_ironman_operator")
    assert status_tool.annotations.read_only_hint is True
    assert status_tool.annotations.destructive_hint is False
    assert status_tool.annotations.idempotent_hint is True
    assert status_tool.input_schema["properties"] == {}
    assert status_tool.name in _TOOL_HANDLERS
    assert operator_tool.annotations.read_only_hint is False
    assert operator_tool.annotations.idempotent_hint is False
