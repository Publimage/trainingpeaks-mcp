from pathlib import Path


def test_active_roster_canary_has_ten_and_excludes_marco():
    text = Path("scripts/ironman_jobs/private_bridge_active_roster_canary_20261017.py").read_text()
    assert text.count('"') > 20
    assert '"2932097"' in text
    assert '"4480273"' in text
    assert '"3737499"' not in text
    assert "/v1/radar-input" in text
    assert "trainingpeaks_writes" in text
