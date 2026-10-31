from pathlib import Path
import ast
def test_diagnostic_is_offline():
    s=(Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/trainingpeaks_organization_test_diagnostic.py").read_text()
    ast.parse(s)
    assert "tests/test_tools/test_organization.py" in s
    for bad in ("TPClient","httpx","requests.","curl ","/plans/","/coaches/"):
        assert bad not in s
