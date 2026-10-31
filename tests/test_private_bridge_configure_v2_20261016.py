from pathlib import Path


def test_private_bridge_config_v2_has_prefect_only_writer():
    text = Path("scripts/ironman_jobs/private_bridge_configure_v2_20261016.py").read_text()
    assert '"result_writer_sources": ["10.114.0.3"]' in text
    assert '"allowed_athletes": ["2932097"]' in text
    assert "provider_writes" in text
