from pathlib import Path
P=Path("scripts/ironman_jobs/image_runtime_capability_inventory_20261017.py")
def test_safe():
    t=P.read_text()
    assert "shutil.which" in t
    assert "PIL" in t
