from pathlib import Path


def test_fit_catalog_audit_checks_tool_and_handler():
    text = Path("scripts/ironman_jobs/fit_reader_catalog_audit.py").read_text(encoding="utf-8")
    assert '"tp_get_workout_fit_data"' in text
    assert "FIT_TOOL_CATALOG_PASS" in text
    assert "_TOOL_HANDLERS" in text
