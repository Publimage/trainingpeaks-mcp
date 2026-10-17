from pathlib import Path
import ast


def test_bridge_v3_has_ten_active_athletes_and_excludes_marco():
    text = Path("scripts/ironman_jobs/private_bridge_configure_v3_multiathlete_20261017.py").read_text()
    assert '"2932097"' in text
    assert '"4480273"' in text
    assert '"3737499"' not in text
    assert "PRIVATE_BRIDGE_CONFIG_V3_MULTIATHLETE_PASS" in text
    assert "provider_writes" in text
