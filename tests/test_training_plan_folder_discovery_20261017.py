from pathlib import Path

def test_readonly_plan_folder_discovery():
    c=Path("scripts/ironman_jobs/training_plan_folder_discovery_20261017.py").read_text()
    assert "await c.get" in c
    assert "await c.post" not in c
    assert "await c.put" not in c
    assert "await c.delete" not in c
