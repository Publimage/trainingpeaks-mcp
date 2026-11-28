from pathlib import Path
P=Path("scripts/ironman_jobs/spaces_canonical_logo_e2e_20261017.py")
def test_contract():
    t=P.read_text()
    assert "tp_publish_public_asset" in t
    assert "ad2710edac3834c467331d2497716c45f8e4cdaf37eaeb658203d531ea9ceea6" in t
    assert "shared/canary/" in t
