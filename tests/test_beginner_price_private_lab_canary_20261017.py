from pathlib import Path
import ast
p=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/beginner_price_private_lab_canary_20261017.py"
def test_price_canary_is_private_only():
    s=p.read_text(encoding="utf-8")
    ast.parse(s)
    assert "LAB=684484" in s
    assert "OWNER=2116886" in s
    assert "679801" not in s
    assert "isPublic" in s and "LAB_BECAME_PUBLIC" in s
    assert "_retry_on_401=False" in s
    assert "LAB_FINAL_METADATA_DRIFT" in s
    assert "LAB_PRICE_NOT_RESTORED" in s
    assert "PRICE_CANARY_PASS" in s
    assert '"DELETE"' not in s and '"POST"' not in s
