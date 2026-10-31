import ast
from pathlib import Path
def test_pdf_source_probe_is_readonly():
 s=Path("scripts/ironman_jobs/winter_pdf_source_probe_20261031.py").read_text()
 ast.parse(s)
 assert "OWNER=2116886" in s and "PLAN=689369" in s and "ATT=105393" in s
 assert "c._client.get" in s and "PROVIDER_WRITES:0" in s
 assert not any(x in s for x in ("c.post(","c.put(","c.delete("))
