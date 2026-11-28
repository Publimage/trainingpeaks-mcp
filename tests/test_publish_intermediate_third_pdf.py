from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/publish_intermediate_third_pdf.py"
def test_scoped_provider_write_and_existing_attachments():
 s=P.read_text();ast.parse(s)
 assert "PLAN=684602" in s and "README=2653899" in s and "OWNER=2116886" in s
 assert "PREVIOUS={(95193" in s and "95194" in s
 assert "SHA=" in s and "hashlib.sha256(data)" in s
 assert "len(before)==35" in s and "sign(original)==PREVIOUS" in s
 assert "PREVIOUS.issubset(actual)" in s
 assert "INTERMEDIATE_THIRD_NATIVE_PDF_ATTACHED_VERIFIED" in s
 assert s.count('"POST"')==1 and '"DELETE"' not in s and '"PUT"' not in s
