from pathlib import Path


def test_live_allowlist_probe_is_read_only():
    text = Path("scripts/ironman_jobs/private_bridge_live_allowlist_probe_20261017.py").read_text()
    assert '"4480273"' in text
    assert "/v1/radar-input" in text
    assert "start_date" in text
    assert "write_text" not in text
