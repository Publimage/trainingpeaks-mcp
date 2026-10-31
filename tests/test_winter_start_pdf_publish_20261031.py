import ast
from pathlib import Path
def test_winter_start_note_pdf_guarded_scope():
 p=Path("scripts/ironman_jobs/winter_start_pdf_publish_20261031.py")
 s=p.read_text(encoding="utf-8")
 ast.parse(s)
 required=['OWNER=2116886','PLAN=689369','PLAN_NOTE=2685704','SOURCE_FILE_ID=105393','ATHLETE=6133559','OLD_NOTE=99784204','LIB=3892900','SHA=','LIBRARY_START_WITH_PDF_VERIFIED','CESARE_NEW_START_PDF_VERIFIED','COMPLETE_PROVIDER_VERIFIED']
 assert all(x in s for x in required)
 assert s.index('LIBRARY_START_WITH_PDF_VERIFIED')<s.index('CESARE_REPLACEMENT_NOTE_CREATED')
 assert s.index('PREDELETE_REPLACEMENT_NOT_VERIFIED')<s.index('deletion=await c.delete(')
 assert 'SOURCE_PDF_HASH_MISMATCH' in s and 'CESARE_OLD_START_UNEXPECTED_ATTACHMENT' in s
