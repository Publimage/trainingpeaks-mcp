from pathlib import Path
def test_inventory_never_reads_secret():
    t=Path("scripts/ironman_jobs/spaces_config_path_inventory_20261017.py").read_text()
    assert ".read_text" not in t
    assert "secret_access_key" not in t
    assert "spaces-uploader.json" in t
