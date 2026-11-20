import ast
from pathlib import Path
def test_scoped_pdf_note_library_probe():
 s=Path("scripts/ironman_jobs/winter_start_library_pdf_lab_20261031.py").read_text(encoding="utf-8")
 ast.parse(s)
 for x in ['LAB_LIB=3924002','PLAN=689369','ATT=105393','OWNER=2116886','NATIVE_NOTE_TEMPLATE_TYPE_FAIL','SOURCE_PDF_HASH_MISMATCH']:
  assert x in s
 assert 'athlete_writes=0' in s
 assert 'c.delete(' not in s
