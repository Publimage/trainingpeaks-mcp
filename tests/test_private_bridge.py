from __future__ import annotations

import json
from pathlib import Path

import pytest

from tp_mcp.private_bridge import _load_config, _persist_admin_result, _validate_window


def test_config_requires_private_bind(tmp_path: Path):
    p = tmp_path / "bridge.json"
    p.write_text(json.dumps({
        "host": "0.0.0.0",
        "port": 8787,
        "allowed_sources": ["10.114.0.3"],
        "allowed_athletes": ["2932097"],
        "result_writer_sources": ["10.114.0.3"],
        "max_window_days": 21,
    }))
    with pytest.raises(RuntimeError, match="PRIVATE_BIND_REQUIRED"):
        _load_config(p)


def test_config_accepts_exact_staging_shape(tmp_path: Path):
    p = tmp_path / "bridge.json"
    p.write_text(json.dumps({
        "host": "10.114.0.2",
        "port": 8787,
        "allowed_sources": ["10.114.0.2", "10.114.0.3"],
        "allowed_athletes": ["2932097"],
        "result_writer_sources": ["10.114.0.3"],
        "max_window_days": 21,
    }))
    cfg = _load_config(p)
    assert cfg["host"] == "10.114.0.2"
    assert cfg["port"] == 8787
    assert cfg["allowed_athletes"] == {"2932097"}


def test_window_is_bounded():
    _validate_window("2026-10-01", "2026-10-21", 21)
    with pytest.raises(ValueError, match="DATE_WINDOW_TOO_LARGE"):
        _validate_window("2026-10-01", "2026-10-22", 21)


def test_admin_result_persist_is_private_and_bounded(tmp_path, monkeypatch):
    import tp_mcp.private_bridge as bridge

    monkeypatch.setattr(bridge, "ADMIN_RESULT_DIR", tmp_path)
    payload = {
        "schema": "IRONMAN_PREFECT_ADMIN_RESULT_V1",
        "job_id": "bootstrap-status-20261016-001",
        "operation": "status",
        "state": "COMPLETED",
        "source_host": "ironman-prefect-staging",
        "started_at_utc": "2026-10-16T20:00:00+00:00",
        "finished_at_utc": "2026-10-16T20:00:01+00:00",
        "exit_code": 0,
        "revision": None,
        "details": {"prefect_server": "active"},
        "output": "ok",
        "trainingpeaks_writes": 0,
    }
    result = _persist_admin_result(payload, {"allowed_athletes": {"2932097"}})
    assert result["stored"] is True
    assert (tmp_path / "latest.json").exists()
    assert (tmp_path / "bootstrap-status-20261016-001.json").exists()


def test_admin_result_rejects_unallowlisted_operation(tmp_path, monkeypatch):
    import tp_mcp.private_bridge as bridge

    monkeypatch.setattr(bridge, "ADMIN_RESULT_DIR", tmp_path)
    payload = {
        "schema": "IRONMAN_PREFECT_ADMIN_RESULT_V1",
        "job_id": "bad-command-20261016-001",
        "operation": "shell",
        "state": "COMPLETED",
        "source_host": "ironman-prefect-staging",
        "trainingpeaks_writes": 0,
    }
    with pytest.raises(ValueError, match="ADMIN_RESULT_OPERATION_INVALID"):
        _persist_admin_result(payload, {"allowed_athletes": {"2932097"}})


def test_admin_receipt_redacts_credential_headers_and_inline_secrets(tmp_path, monkeypatch):
    import tp_mcp.private_bridge as bridge

    # Synthetic strings only: no real provider credentials in tests.
    example = (
        "phase=ok\\n"
        "Authorization: Bearer DEMO_AUTH_VALUE\\n"
        "Cookie: session=DEMO_COOKIE_A; pref=DEMO_COOKIE_B\\n"
        "token=DEMO_INLINE_TOKEN\\n"
        "api_key: DEMO_API_KEY\\n"
        "Bearer DEMO_STANDALONE_VALUE\\n"
        "normal status survives"
    )
    sanitized = bridge._redact_admin_text(example)
    for forbidden in (
        "DEMO_AUTH_VALUE", "DEMO_COOKIE_A", "DEMO_COOKIE_B",
        "DEMO_INLINE_TOKEN", "DEMO_API_KEY", "DEMO_STANDALONE_VALUE",
    ):
        assert forbidden not in sanitized
    assert "normal status survives" in sanitized
    assert sanitized.count("[redacted]") >= 5

    monkeypatch.setattr(bridge, "ADMIN_RESULT_DIR", tmp_path)
    payload = {
        "schema": "IRONMAN_PREFECT_ADMIN_RESULT_V1",
        "job_id": "security-test-20261025",
        "operation": "status",
        "state": "COMPLETED",
        "source_host": "ironman-prefect-staging",
        "output": example,
        "trainingpeaks_writes": 0,
    }
    bridge._persist_admin_result(payload, {"allowed_athletes": set()})
    stored = (tmp_path / "latest.json").read_text(encoding="utf-8")
    assert "DEMO_AUTH_VALUE" not in stored
    assert "DEMO_INLINE_TOKEN" not in stored
    assert "[redacted]" in stored
