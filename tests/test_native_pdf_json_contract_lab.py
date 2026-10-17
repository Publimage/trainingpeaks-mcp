from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/native_pdf_json_contract_lab.py"
def test_invalid_only_and_lab():
 t=P.read_text();ast.parse(t)
 assert "LAB=684484" in t and "NOTE=2655001" in t and "OWNER=2116886" in t
 assert "684602" not in t and "json={}" in t
 assert "EMPTY_JSON_REJECTED_UNCHANGED" in t and "after==before" in t
