"""Static scope for README description-only public Intermediate plan."""
import ast
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/intermediate_readme_current_guides_20261022.py"
def test_guardrails():
    s=P.read_text("utf-8")
    ast.parse(s)
    assert "PLAN=684602;NOTE=2653899;OWNER=2116886;PERSON=6678583" in s
    assert "len(x.data)==35" in s and "isPublic" in s and "price" in s
    assert 'payload["description"]=body.replace(BEFORE,AFTER)' in s
    assert 'signature(new)==ATT' in s
    for forbidden in ('await c.delete(', 'await c.post(', '/workouts/save', '/libraryContent/'):
        assert forbidden not in s
