from __future__ import annotations

import json

import pytest

from tp_mcp.tools import radar


@pytest.mark.asyncio
async def test_radar_latest_readback(tmp_path, monkeypatch):
    monkeypatch.setattr(radar, "RADAR_RESULT_DIR", tmp_path)
    payload = {
        "schema": "IRONMAN_COACHING_RADAR_V1",
        "athlete_id": 2932097,
        "as_of": "2026-10-16",
        "trainingpeaks_writes": 0,
        "alerts": [],
    }
    (tmp_path / "latest_2932097.json").write_text(json.dumps(payload))
    result = await radar.tp_get_coaching_radar("2932097")
    assert result == payload


@pytest.mark.asyncio
async def test_radar_invalid_athlete():
    result = await radar.tp_get_coaching_radar("abc")
    assert result["isError"] is True
    assert result["error_code"] == "VALIDATION_ERROR"
