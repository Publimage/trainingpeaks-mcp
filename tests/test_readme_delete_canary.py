"""Offline safety regression for disposable note deletion route probe."""
import ast
from pathlib import Path
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/readme_delete_canary.py"

def test_lab_only_protection():
    s=S.read_text()
    ast.parse(s)
    assert "LAB = 684484" in s and "OWNER = 2116886" in s
    assert "Intermediate plan" in s and "684602" not in s
    assert '"DELETE"' in s and '"POST"' in s
    assert "ANCHOR_ID = 2651317" in s
    assert "_retry_on_401=False" in s
    assert "original_snapshot" in s
    assert "CANARY_DELETE_VERIFIED" in s
