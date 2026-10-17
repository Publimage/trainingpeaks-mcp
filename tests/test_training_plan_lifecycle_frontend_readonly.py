from pathlib import Path
import ast

P = Path(__file__).resolve().parents[1] / "scripts/ironman_jobs/training_plan_lifecycle_frontend_readonly.py"

def test_public_readonly():
    s = P.read_text(encoding="utf-8")
    ast.parse(s)
    assert 'BASE="https://app.trainingpeaks.com/"' in s
    assert r'\.copyTrainingPlan\(' in s
    assert '"stage":"COPY_CALL"' in s
    for bad in ("TPClient", "Authorization", "Bearer ", "h.post(", "h.put(", "h.delete("):
        assert bad not in s
    assert '"provider_writes":0' in s
