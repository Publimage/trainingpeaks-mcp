"""Offline checks for the reusable PDF-attachment cleanup runner."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "scripts/ironman_jobs/reviewed_note_attachment_cleanup_common.py"
PREVIEW = ROOT / "scripts/ironman_jobs/reviewed_note_attachment_cleanup_preview.py"
PUBLISH = ROOT / "scripts/ironman_jobs/reviewed_note_attachment_cleanup_publish.py"
MANIFEST = ROOT / "data/ironman_reviewed_note_attachment_cleanup.json"


def test_code_compiles_and_entrypoints_are_mode_separated():
    for file in (CORE, PREVIEW, PUBLISH):
        ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    assert "main(False)" in PREVIEW.read_text(encoding="utf-8")
    assert "main(True)" in PUBLISH.read_text(encoding="utf-8")
    core = CORE.read_text(encoding="utf-8")
    assert "if not publish:" in core
    assert "_retry_on_401=False" in core
    assert "FINAL_THREE_PDFS_MISMATCH" in core
    assert "OWNER" not in core or "owner_person_id" in core


def test_reviewed_manifest_is_exact_and_retains_three_current_pdfs():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert m["schema"] == "IRONMAN_NOTE_ATTACHMENT_CLEANUP_V1"
    assert m["configured"] is True
    assert m["owner_person_id"] == 2116886
    assert m["plan_id"] == 684602 and m["note_id"] == 2653899
    assert m["plan_public"] is True and m["plan_price"] == 179
    assert m["plan_workout_count"] == 259 and m["plan_notes_count"] == 35
    items = m["attachments"]
    assert len(items) == 5
    assert len({x["id"] for x in items}) == 5
    assert {x["id"] for x in items if x["action"] == "remove"} == {95193, 95228}
    assert {x["id"] for x in items if x["action"] == "keep"} == {95194, 98909, 98910}
    assert all(x["bytes"] > 100 and x["name"].endswith(".pdf") for x in items)
