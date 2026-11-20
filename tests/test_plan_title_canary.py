from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/plan_title_canary.py"
def test_guarded_lab_only():
    t=S.read_text()
    ast.parse(t)
    assert "PLAN=684484" in t and "OWNER=2116886" in t
    assert "684602" not in t and "OLD=" in t and "NEW=" in t
    assert '"PUT"' in t and t.count("_retry_on_401=False")==2
    assert "CANARY_RESTORED_VERIFIED" in t and "CANARY_NOTES_DRIFT" in t
