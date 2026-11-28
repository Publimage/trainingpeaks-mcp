from pathlib import Path

def test_finalize_scope_is_exact():
    p=Path("scripts/ironman_jobs/francesco_winter_finalize.py").read_text()
    assert "ATHLETE=5590716" in p
    assert "PLAN=689369" in p
    assert "TARGET_NOTE=99785295" in p
    assert "len(arr)==16" in p
    assert "PDF_SIZE=407035" in p
    assert 'PDF_SHA="7f947d35e81ea4a7fb423ccd19441f2ade5646dda025ce0bda41a2ce98fd3c1b"' in p
    assert '"/rx/activity/v1/workouts/save"' in p
    assert "tp_delete" not in p
    assert "DELETE" not in p
