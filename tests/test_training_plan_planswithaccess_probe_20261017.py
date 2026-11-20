from pathlib import Path
P=Path("scripts/ironman_jobs/training_plan_planswithaccess_probe_20261017.py")
def test_read_only():
 s=P.read_text()
 assert 'c.get("/plans/v1/plansWithAccess")' in s
 assert "c.post(" not in s and "c.put(" not in s and "c.delete(" not in s
