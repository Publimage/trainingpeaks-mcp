from pathlib import Path


def test_private_bridge_live_job_is_read_only():
    text = Path("scripts/ironman_jobs/private_bridge_live_selftest_20261016.py").read_text()
    assert "http://10.114.0.2:8787" in text
    assert '"athlete_id": "2932097"' in text
    assert '"trainingpeaks_writes"' in text
    assert "urllib.request" in text
