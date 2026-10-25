from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/test_lab_note_pdf_upload.py"
def test_exact_lab_note_and_file():
 s=S.read_text();ast.parse(s)
 assert "LAB=684484" in s and "NOTE=2655001" in s and "OWNER=2116886" in s
 assert "684602" not in s and "2653899" not in s
 assert 'files={"file":(FILENAME,data,"application/pdf")}' in s
 assert "LAB_ALREADY_HAS_ATTACHMENTS" in s and "LAB_ATTACHMENT_VERIFIED" in s
 assert "SHA=" in s and "hashlib.sha256" in s
 assert '"DELETE"' not in s and '"PUT"' not in s
