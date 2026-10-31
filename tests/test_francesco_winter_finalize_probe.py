from pathlib import Path

def test_probe_is_read_only():
    p=Path("scripts/ironman_jobs/francesco_winter_finalize_probe.py").read_text()
    assert 'request("GET"' in p
    assert 'request("POST"' not in p
    assert 'request("PUT"' not in p
    assert 'request("DELETE"' not in p
    assert "ATHLETE=5590716" in p
    assert "PLAN=689369" in p
