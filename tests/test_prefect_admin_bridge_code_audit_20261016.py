from pathlib import Path


def test_prefect_admin_sink_audit_is_local_only():
    text = Path("scripts/ironman_jobs/prefect_admin_bridge_code_audit_20261016.py").read_text()
    assert "TemporaryDirectory" in text
    assert "_persist_admin_result" in text
    assert "PREFECT_ADMIN_SINK_LOCAL_AUDIT_PASS" in text
