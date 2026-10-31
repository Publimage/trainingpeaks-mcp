from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/cleanup_intermediate_pdf_lab.py"
def test_cleanup_only_temp_lab():
 s=P.read_text();ast.parse(s)
 assert "LAB=684484" in s and "LAB_NOTE=2655001" in s and "OWNER=2116886" in s
 assert '"/plans/v1/plans/684602/calendarNote/2026-10-05/2027-04-01"' in s
 assert "target_pdfs" in s and "95228" in s and "95227" in s
 assert "PDF.unlink()" in s and "LAB_TEMP_NOTE_DELETED_AND_VERIFIED" in s
 assert s.count('"DELETE"')==1 and '"POST"' not in s and '"PUT"' not in s
