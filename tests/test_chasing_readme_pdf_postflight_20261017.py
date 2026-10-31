from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/chasing_readme_pdf_postflight_20261017.py"
def test_read_only_exact_attachment_inventory():
 s=P.read_text(); ast.parse(s)
 assert "PLAN=685173" in s and "NOTE=2664007" in s and "OWNER=2116886" in s
 assert "97221" in s and "97222" in s and "97223" in s
 assert "CHASING_README_PDF_POSTFLIGHT_PASS" in s
 assert '"POST"' not in s and '"PUT"' not in s and '"DELETE"' not in s
