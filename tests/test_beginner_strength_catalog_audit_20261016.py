from pathlib import Path
import ast
def test_beginner_strength_catalog_audit_is_read_only():
 s=Path("scripts/ironman_jobs/beginner_strength_catalog_audit_20261016.py").read_text()
 ast.parse(s)
 assert "BEGINNER_STRENGTH_CATALOG_PASS" in s
 assert "tp_batch_add_beginner_strength" in s
 assert "tp_batch_delete_beginner_classic_strength" in s
