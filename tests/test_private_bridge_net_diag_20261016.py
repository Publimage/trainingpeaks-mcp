from pathlib import Path
def test_diag_is_read_only():
    t=Path("scripts/ironman_jobs/private_bridge_net_diag_20261016.py").read_text()
    assert '"ss","-ltnp"' in t
    assert '"ufw","status","numbered"' in t
    assert "allow" not in t
