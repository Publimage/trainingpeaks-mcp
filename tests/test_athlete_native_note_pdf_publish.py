"""Static safety tests for a generic athlete-note PDF publisher."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ironman_jobs/athlete_native_note_pdf_publish.py"
MANIFEST = ROOT / "data/ironman_athlete_note_pdf_manifest.json"


def test_source_and_target_pinned_and_safe():
    code = SCRIPT.read_text(encoding="utf-8")
    ast.parse(code)
    cfg = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert cfg["schema"] == "IRONMAN_ATHLETE_NOTE_PDF_V1"
    assert cfg["owner_id"] == 2116886
    assert cfg["athlete_id"] == 4480273
    assert cfg["target_note_id"] == 100766794
    assert cfg["source_plan_id"] == 689369
    assert cfg["source_plan_note_id"] == 2685704
    assert cfg["source_attachment_id"] == 105393
    assert cfg["expected_athlete_note_count"] == 9
    assert cfg["sha256"] == "7f947d35e81ea4a7fb423ccd19441f2ade5646dda025ce0bda41a2ce98fd3c1b"
    assert "SOURCE_BINARY_HASH_MISMATCH" in code
    assert "TARGET_NOTE_ID_DATE_OR_BODY_DRIFT" in code
    assert "AFTER_NOTE_INVENTORY_CHANGED" in code
    assert "POST_NOT_VERIFIED_STATUS_" in code
    assert "never retry POST" in code
    assert "c.delete(" not in code
    assert '"/attachments"' in code
