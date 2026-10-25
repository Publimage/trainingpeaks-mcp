from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/native_pdf_json_fields_lab.py"
def test_only_safe_validation_requests():
 s=S.read_text();ast.parse(s)
 assert "LAB=684484" in s and "NOTE=2655001" in s
 assert "684602" not in s and "baseline=await notes()" in s
 assert 'if res.status_code!=400:' in s and "STOP_PROVIDER_CHANGED" in s
 assert "fileName" not in s and "base64" not in s
