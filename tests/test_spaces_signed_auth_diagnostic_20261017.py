from pathlib import Path
P=Path("scripts/ironman_jobs/spaces_signed_auth_diagnostic_20261017.py")
def test_diag_is_read_only_and_secret_safe():
    t=P.read_text()
    assert 'client.get(' in t
    assert 'client.put(' not in t
    assert 'secret_access_key"]' in t
    assert 'print(cfg' not in t
    assert 'OBJECT_KEY="shared/__ironman_spaces_auth_probe_nonexistent__"' in t
