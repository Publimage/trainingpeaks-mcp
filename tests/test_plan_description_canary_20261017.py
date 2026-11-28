from pathlib import Path
P=Path("scripts/ironman_jobs/plan_description_canary_20261017.py")
def test_contract():
    t=P.read_text()
    assert "PLAN=684484" in t
    assert '"description":CANARY' in t
    assert '"description":old' in t
    assert "_retry_on_401=False" in t
