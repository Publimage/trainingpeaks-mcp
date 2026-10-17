from pathlib import Path

P=Path("scripts/ironman_jobs/spaces_credential_shape_diagnostic_20261017.py")

def test_secret_safe():
    t=P.read_text()
    assert "SPACES_CREDENTIAL_SHAPE" in t
    assert "print(cfg" not in t
    assert "len(value)" in t
