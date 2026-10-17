from pathlib import Path
P=Path("scripts/ironman_jobs/intermediate_marketplace_metadata_recovery_20261017.py")
def test_contract():
    t=P.read_text()
    assert "TARGET=684602" in t
    assert "SOURCE=684463" in t
    assert '"planLanguage":src["planLanguage"]' in t
    assert '"description":p["description"]' in t
    assert "_retry_on_401=False" in t
