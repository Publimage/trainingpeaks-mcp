from pathlib import Path
P=Path("scripts/ironman_jobs/training_plan_planswithaccess_module_scan_20261017.py")
def test_read_only():
 s=P.read_text()
 assert 'NEEDLE="/plans/v1/plansWithAccess"' in s
 assert "await h.get" in s
 assert "await h.post" not in s and "await h.put" not in s and "await h.delete" not in s
