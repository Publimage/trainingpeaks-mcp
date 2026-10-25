"""Static gates: Intermediate plan-scoped native note only, no athlete writes."""
import ast
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/intermediate_monday_native_notes_20261022.py"
def test_scope():
    source=P.read_text("utf-8")
    ast.parse(source)
    assert "PLAN=684602" in source and "OWNER=2116886" in source and "PERSON=6678583" in source
    assert "NOTES={1:2654984,2:2652651,3:2652952,5:2652955,6:2652956,7:2652983}" in source
    assert "len(r.data)==35" in source and "workoutCount" in source and "price" in source
    assert "if canary else [2,3,5,6,7]" in source
def test_is_only_native_note_put():
    source=P.read_text("utf-8")
    assert 'f"/plans/v1/plans/{PLAN}/calendarNote/{nid}"' in source
    assert 'payload["description"]=' in source
    assert "attachments" in source
    assert "_retry_on_401=False" in source
    assert "INTERMEDIATE_NOTE_WRITE_VERIFIED" in source
    for forbidden in ("/libraryContent/", "/workouts/save", "await c.delete(", "await c.post("):
        assert forbidden not in source
