"""Offline regression for README FIRST read-only note-order diagnostic."""
from pathlib import Path
import ast

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ironman_jobs/readme_first_order_audit.py"

def test_exact_scope_and_no_provider_writes():
    s = SCRIPT.read_text()
    tree = ast.parse(s)
    assert "PLAN_ID = 684602" in s
    assert "OWNER_ID = 2116886" in s
    assert "2653899" in s
    assert "2653513" in s and "2653514" in s
    assert "len(r.data) == 35" in s
    methods = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "post" not in methods and "put" not in methods and "delete" not in methods
    assert "get" in methods
