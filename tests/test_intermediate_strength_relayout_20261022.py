"""Offline checks for exact native Strength relocation scope."""
import ast
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/intermediate_strength_relayout_20261022.py"
def test_scope_and_approved_count():
    text=P.read_text(encoding="utf-8")
    ast.parse(text)
    assert "PLAN=684602" in text
    assert "PERSON=6678583" in text
    assert "OWNER=2116886" in text
    assert "len(MOVES)==22" in text
    assert "CANARY_ID=33973536" in text
def test_inplace_only_and_structural_readback():
    text=P.read_text(encoding="utf-8")
    assert "payload=copy.deepcopy(current)" in text
    assert 'payload["title"]=t["title_after"]' in text
    assert 'payload["prescribedDate"]=t["to"]' in text
    assert "sha(final.get(\"blocks\"))==t[\"block_sha\"]" in text
    assert "len(after)" in text
    assert "httpx.AsyncClient" in text
    for forbidden in ("/workouts/delete","/libraryContent/workoutLibrary","await h.delete(", "await c.post("):
        assert forbidden not in text
