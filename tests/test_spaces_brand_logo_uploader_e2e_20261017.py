from pathlib import Path

def test_scoped_uploader_canary():
    t=Path("scripts/ironman_jobs/spaces_brand_logo_uploader_e2e_20261017.py").read_text()
    assert "tp_publish_public_asset" in t
    assert 'OBJECT_KEY="brand/logo/alberto-fazi-endurance-logo-v1.0.png"' in t
    assert 'EXPECTED_SIZE=112958' in t
    assert "3960fee00da0596141c64ffa3b554d6d9478baea212cec3440795d6275e360ab" in t
    assert "secret_access_key" not in t
