from pathlib import Path
import ast
def test_readonly_preview_scoped():
 p=Path("scripts/ironman_jobs/beginner_rpe_native_preview_20261016.py")
 s=p.read_text();ast.parse(s)
 assert "preflight(c)" in s
 for x in ("._request(",".put(",".post(",".patch(",".delete("):assert x not in s
def test_native_compiler_scoped():
 s=Path("scripts/ironman_jobs/beginner_rpe_native_common_20261016.py").read_text()
 ast.parse(s)
 assert "PLAN=679801" in s and "OWNER=2116886" in s
 assert 'row["source_rpe_clauses"]' not in s or "RPE_SOURCE_MISSING" in s
 assert "CADENCE_CHANGED" in s and "DOSE_CHANGED" in s
 for x in ("._request(",".put(",".post(",".patch(",".delete("):assert x not in s
