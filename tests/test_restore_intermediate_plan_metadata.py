from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/restore_intermediate_plan_metadata.py"
def test_no_extra_writes():
 s=P.read_text();ast.parse(s)
 assert "TARGET=684602" in s and "SOURCE=684463" in s and "OWNER=2116886" in s
 assert "RENAME_AND_METADATA_VERIFIED" in s and '"planEmail":s["planEmail"]' in s
 assert '"PUT"' in s and '"POST"' not in s and '"DELETE"' not in s
 assert "NOTES_CHANGED" in s and "PLAN_CORE_CHANGED" in s
