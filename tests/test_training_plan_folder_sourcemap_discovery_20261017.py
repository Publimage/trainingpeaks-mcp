from pathlib import Path
P=Path("scripts/ironman_jobs/training_plan_folder_sourcemap_discovery_20261017.py")
def test_readonly_sourcemap_discovery():
 s=P.read_text()
 assert "await h.get" in s
 assert "await h.post" not in s and "await h.put" not in s and "await h.delete" not in s
 assert "sourceMappingURL" in s
