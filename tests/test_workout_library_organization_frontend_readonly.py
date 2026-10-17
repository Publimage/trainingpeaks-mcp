from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/workout_library_organization_frontend_readonly.py"
def test_public_readonly():
    s=P.read_text();ast.parse(s)
    assert "https://app.trainingpeaks.com/" in s
    assert "apiProxy.moveWorkoutToLibrary" in s
    for bad in ("TPClient","Authorization","Bearer ","h.post(","h.put(","h.delete("):
        assert bad not in s
    assert '"provider_writes":0' in s
