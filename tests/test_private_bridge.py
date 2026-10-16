from __future__ import annotations

import json
from pathlib import Path

import pytest

from tp_mcp.private_bridge import _load_config, _validate_window


def test_config_requires_private_bind(tmp_path: Path):
    p = tmp_path / "bridge.json"
    p.write_text(json.dumps({
        "host": "0.0.0.0",
        "port": 8787,
        "allowed_sources": ["10.114.0.3"],
        "allowed_athletes": ["2932097"],
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
