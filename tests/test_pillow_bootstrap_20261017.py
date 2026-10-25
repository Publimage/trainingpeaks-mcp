from pathlib import Path
P=Path("scripts/ironman_jobs/pillow_bootstrap_20261017.py")
def test_contract():
    t=P.read_text()
    assert 'Pillow==11.3.0' in t
    assert 'pip' in t
    assert 'PILLOW_BOOTSTRAP_PASS' in t
