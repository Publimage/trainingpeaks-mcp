import ast
from pathlib import Path
def test_lab_pdf_probe_is_scoped():
 p=Path("scripts/ironman_jobs/winter_start_pdf_lab_20261031.py")
 s=p.read_text(encoding="utf-8")
 ast.parse(s)
 assert "LAB=941614" in s and 'DAY="2028-12-11"' in s
 assert "OWNER=2116886" in s
 assert "/fitness/v1/athletes/{LAB}/calendarNote" in s
 assert "c.delete" in s and "LAB_CLEANUP_UNVERIFIED" in s
