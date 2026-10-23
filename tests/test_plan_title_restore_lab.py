from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/plan_title_restore_lab.py"
def test_lab_guard():
 s=S.read_text();ast.parse(s)
 assert "LAB=684484" in s and "684602" not in s and "OWNER=2116886" in s
 assert 'OLD+" | TITLE CANARY"' in s and 'str(x.error_code)' in s
