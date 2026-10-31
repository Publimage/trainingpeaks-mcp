from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/plan_metadata_audit.py"
def test_readonly():
 s=P.read_text();ast.parse(s)
 assert "OWNER=2116886" in s and "684602" in s and "679801" in s
 assert '"PUT"' not in s and '"POST"' not in s and '"DELETE"' not in s
 assert "NO_PROVIDER_WRITES" in s
