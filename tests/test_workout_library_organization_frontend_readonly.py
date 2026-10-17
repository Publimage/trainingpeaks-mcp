from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/workout_library_organization_frontend_readonly.py"
def test_public_readonly():
    s=P.read_text();ast.parse(s)
    assert "modules-6ddaaa87.js" in s
    assert "deleteActivityFromLibrary" in s
    assert "updateActivityInLibrary" in s
    assert "renameLibrary" in s
    for bad in ("TPClient","Authorization","Bearer ","h.post(","h.put(","h.delete("):
        assert bad not in s
    assert '"provider_writes":0' in s
