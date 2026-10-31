from pathlib import Path
P=Path("scripts/ironman_jobs/tp_openapi_planfolder_discovery_20261017.py")
def test_read_only():
 s=P.read_text()
 assert "await c.get(path)" in s
 assert "await c.post" not in s and "await c.put" not in s and "await c.delete" not in s
 assert "swagger" in s and "openapi" in s
