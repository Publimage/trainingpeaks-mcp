from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/test_lab_note_pdf_json.py"
def test_only_exact_lab_with_full_pdf():
 s=S.read_text();ast.parse(s)
 assert "LAB=684484" in s and "NOTE=2655001" in s and "OWNER=2116886" in s
 assert "684602" not in s and "2653899" not in s
 assert 'payload={"planId":LAB,"noteId":NOTE,"fileName":FILENAME,' in s
 assert '"data":base64.b64encode(data).decode("ascii")' in s
 assert "LAB_JSON_PDF_UPLOADED_VERIFIED" in s and "SHA=" in s
 assert "REJECTED_BUT_ATTACHMENT_EXISTS_STOP" in s
