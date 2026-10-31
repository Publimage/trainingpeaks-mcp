from pathlib import Path

def test_public_check_is_read_only():
    t=Path("scripts/ironman_jobs/spaces_brand_logo_public_check_20261017.py").read_text()
    assert "urlopen(PUBLIC_URL" in t
    assert 'method="PUT"' not in t
    assert "urllib.request.Request" not in t
    assert "EXPECTED_SHA256" in t
