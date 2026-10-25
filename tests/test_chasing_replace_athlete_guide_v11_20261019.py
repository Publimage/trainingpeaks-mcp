from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/chasing_replace_athlete_guide_v11_20261019.py"
def test_exact_chasing_pdf_replacement_scope():
    s=P.read_text(); ast.parse(s)
    assert "PLAN=685173" in s and "NOTE=2664007" in s and "OWNER=2116886" in s
    assert "Advanced | Italiano" in s
    assert "OLD_ID=97221" in s and "97222" in s and "97223" in s
    assert "Guida Atleta v1.1.pdf" in s
    assert "be871aee7f899e834fc466048606001a19369be84f38fb2b3e35db10a5ff6d3c" in s
    assert '"POST"' in s and '"DELETE"' in s
    assert "AMBIGUOUS_UPLOAD_NO_READBACK_STOP" in s
    assert "AMBIGUOUS_DELETE_UNRESOLVED_STOP" in s
    assert "other_30_notes_unchanged" in s and "start_note_body_unchanged" in s
    assert "CHASING_ATHLETE_GUIDE_V11_REPLACED_VERIFIED" in s
