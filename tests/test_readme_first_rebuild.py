"""Offline checks for one-shot protected README FIRST repair."""
import ast
from pathlib import Path
SRC=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/readme_first_rebuild.py"
def test_exact_scope_and_provider_canary():
    s=SRC.read_text()
    ast.parse(s)
    for term in ("PLAN = 684602","OWNER = 2116886","OLD_PHASE = 2653513","OLD_WEEKLY = 2653514","README = 2653899"):
        assert term in s
    assert "p.get(\"isPublic\") is False" in s
    assert "len(base) == 35" in s and "259" in s and "24" in s
    assert "EXPECTED_ATTACHMENTS" in s and "pdf_signature" in s
    assert "PROTECTED_NOTE_CHANGED" in s
def test_add_before_delete_and_no_unscoped_operations():
    s=SRC.read_text()
    assert s.index('for old in (OLD_PHASE, OLD_WEEKLY):') < s.index('# A tested, plan-scoped DELETE route.')
    assert "POST_CLONE_NOT_UNIQUE" in s
    assert "CREATED_NOTE_NOT_DISPLAYED_AFTER_README" in s
    assert "README_NOT_FIRST" in s and "README_FIRST_VERIFIED" in s
    assert "readback_before_any_retry" in s
    assert s.count("_retry_on_401=False") == 2
    assert "/fitness/v6/athletes/" not in s
    assert "/plans/v1/commands/applyplan" not in s
def test_post_and_delete_only_exact_plan_scoped_notes():
    tree=ast.parse(SRC.read_text())
    attributes={node.attr for node in ast.walk(tree) if isinstance(node,ast.Attribute)}
    assert "delete" not in attributes and "post" not in attributes and "put" not in attributes
    assert "_request" in attributes and "get" in attributes
