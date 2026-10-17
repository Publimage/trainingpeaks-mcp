from pathlib import Path
P=Path("scripts/ironman_jobs/spaces_brand_logo_production_20261017.py")
def test_contract():
    t=P.read_text()
    assert "resize((1200,400)" in t
    assert "3960fee00da0596141c64ffa3b554d6d9478baea212cec3440795d6275e360ab" in t
    assert "target_exists_different" in t
