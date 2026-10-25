from pathlib import Path
P=Path("scripts/ironman_jobs/training_plan_folder_symbol_scan_20261017.py")
def test_read_only_symbol_scan():
 s=P.read_text()
 assert "await c.get" in s
 assert "await c.post" not in s and "await c.put" not in s and "await c.delete" not in s
 assert "movePlanToFolder" in s and "createTrainingPlanFolder" in s
