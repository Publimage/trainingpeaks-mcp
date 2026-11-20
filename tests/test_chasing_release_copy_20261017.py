from pathlib import Path
P=Path("scripts/ironman_jobs/chasing_release_copy_20261017.py")
def test_contract():
    t=P.read_text()
    assert "PLAN=685173" in t
    assert "Advanced | Italiano" in t
    assert "BOZZA" in t
    assert "CHASING_RELEASE_COPY_VERIFIED" in t
    assert "_retry_on_401=False" in t
    assert "isPublic" in t
