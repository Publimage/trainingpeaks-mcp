from pathlib import Path


def test_prefect_ssh_inventory_does_not_print_private_key_contents():
    text = Path("scripts/ironman_jobs/prefect_ssh_inventory_20261016.py").read_text()
    assert '"10.114.0.3"' in text
    assert "socket.create_connection" in text
    assert "read_text" not in text
    assert "private_candidate" in text
    assert "fingerprint" in text
