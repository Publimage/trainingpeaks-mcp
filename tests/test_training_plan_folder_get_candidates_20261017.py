from pathlib import Path
P=Path("scripts/ironman_jobs/training_plan_folder_get_candidates_20261017.py")
def test_read_only():
 s=P.read_text()
 assert "await c.get(path)" in s
 assert "await c.post" not in s and "await c.put" not in s and "await c.delete" not in s
 assert "planFoldersWithAccess" in s and "/plans/v2/" in s
