from pathlib import Path

def test_winter_start_note_pdf_target_and_safety():
    s = Path("scripts/ironman_jobs/winter_start_pdf_publish_20261031.py").read_text(encoding="utf-8")
    for target in ("OWNER=2116886", "PLAN=689369", "PLAN_NOTE=2685704", "SOURCE_FILE_ID=105393", "ATHLETE=6133559", "OLD_NOTE=99784204", "LIB=3892900"):
        assert target in s
    assert "PDF_SOURCE_HASH_MISMATCH" in s
    assert "LIBRARY_PDF_HASH_MISMATCH" in s
    assert "CESARE_FINAL_START_MISMATCH" in s
    assert s.index("PREDELETE_REPLACEMENT_NOT_VERIFIED") < s.index("deletion=await c.delete(")
