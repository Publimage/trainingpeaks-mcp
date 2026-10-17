from pathlib import Path


def test_multi_radar_audit_has_ten_active_athletes_and_no_marco():
    text = Path("scripts/ironman_jobs/coaching_radar_multi_result_audit_20261017.py").read_text()
    assert text.count('": "') >= 10
    assert '"2932097"' in text
    assert '"4480273"' in text
    assert '"3737499"' not in text
    assert "tp_get_coaching_radar" in text
    assert "trainingpeaks_writes" in text
