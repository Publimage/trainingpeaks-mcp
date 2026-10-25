from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/native_note_pdf_json_field_probe.py"
def test_bad_payload_lab_only():
 s=S.read_text();ast.parse(s)
 assert "LAB=684484" in s and "NOTE=2655001" in s and "OWNER=2116886" in s
 assert 'BAD="INVALID_NOT_PDF_@@@"' in s and "684602" not in s
 assert "response.status_code!=400" in s and "after==before" in s
