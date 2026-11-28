from pathlib import Path


def test_radar_result_audit_is_read_only():
    text = Path("scripts/ironman_jobs/coaching_radar_result_audit_20261016.py").read_text()
    assert 'ATHLETE_ID = "2932097"' in text
    assert "tp_get_coaching_radar" in text
    assert "trainingpeaks_writes" in text
    assert "write_text" not in text
