from pathlib import Path


def test_prefect_admin_result_reader_is_read_only():
    text = Path("scripts/ironman_jobs/prefect_admin_result_read_20261016.py").read_text()
    assert "latest.json" in text
    assert "read_text" in text
    assert "write_text" not in text
    assert "PREFECT_ADMIN_RESULT_READ_PASS" in text
