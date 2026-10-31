from pathlib import Path


def test_private_bridge_config_job_is_scoped():
    text = Path("scripts/ironman_jobs/private_bridge_configure_20261016.py").read_text()
    assert '"host": "10.114.0.2"' in text
    assert '"10.114.0.3"' in text
    assert '"allowed_athletes": ["2932097"]' in text
    assert "provider_writes" in text
    assert "0o600" in text
