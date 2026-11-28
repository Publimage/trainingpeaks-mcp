from pathlib import Path

P = Path("scripts/ironman_jobs/spaces_brand_logo_canary_20261017.py")

def test_canary_is_scoped_and_secret_free():
    t=P.read_text()
    assert "ironman-assets.fra1.digitaloceanspaces.com/brand/logo/alberto-fazi-endurance-logo-v1.0.png" in t
    assert "EXPECTED_SIZE = 112958" in t
    assert "3960fee00da0596141c64ffa3b554d6d9478baea212cec3440795d6275e360ab" in t
    assert "x-amz-acl" in t and "public-read" in t
    assert "SPACES_SECRET" not in t
    assert "secret_access_key" not in t
