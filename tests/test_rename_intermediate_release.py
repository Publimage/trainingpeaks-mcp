from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/rename_intermediate_release.py"
def test_only_exact_private_plan_and_name():
 s=S.read_text();ast.parse(s)
 assert "PLAN=684602" in s and "OWNER=2116886" in s
 assert 'NEW="ALBERTO FAZI ENDURANCE | IRONMAN | 24 settimane | Intermediate | Italiano"' in s
 assert "EXPECTED_ORDER=[2653899,2654983,2654984]" in s
 assert "EXPECTED_PDFS" in s and 'json={"planId":PLAN,"title":NEW}' in s
 assert s.count("_retry_on_401=False")==1 and '"PUT"' in s
 assert '"POST"' not in s and '"DELETE"' not in s
 assert "PLAN_RENAMED_VERIFIED" in s and "NOTES_OR_ATTACHMENTS_CHANGED" in s
