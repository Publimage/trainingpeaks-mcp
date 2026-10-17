from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/training_plan_organization_metadata_readonly.py"

def test_readonly_known_endpoints_only():
    s=P.read_text(encoding="utf-8")
    ast.parse(s)
    assert "OWNER=2116886" in s
    assert '"/plans/v1/plans"' in s
    assert '"/plans/v1/plansWithAccess"' in s
    assert 'c.get(f"/plans/v1/plans/{pid}")' in s
    for verb in ('c.post(', 'c.put(', 'c.delete(', 'c.patch(', '._request("POST"', '._request("PUT"', '._request("DELETE"'):
        assert verb not in s
    assert '"provider_writes":0' in s
    assert "684762" in s and "684206" in s and "679801" in s
