from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/note_put_pdf_preservation_lab.py"
def test_lab_only_preflight_guards():
 s=S.read_text();ast.parse(s)
 assert "OWNER=2116886" in s and "LAB=684484" in s
 assert 'TITLE="[MCP TEST] README BODY PDF PRESERVATION CANARY"' in s
 assert "LAB_BODY_UPDATED_ATTACHMENT_PRESERVED" in s
 assert "LAB_NOTE_PUT_WITH_PDF_CANARY_PASS" in s
 assert "LAB_PDF_ATTACHMENT_CHANGED" in s and "LAB_ANCHOR_CHANGED" in s
 assert "2653899" not in s and "98270265" not in s
 assert s.count("_retry_on_401=False")==3
