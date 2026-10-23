from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/training_plan_folder_actions_frontend_readonly.py"
def test_public_only():
    s=P.read_text();ast.parse(s)
    assert "https://app.trainingpeaks.com/" in s
    assert "movePlansBetweenFolders" in s
    assert "assignPlanToFolder" in s
    assert "getFolders" in s
    for bad in ("TPClient","Authorization","Bearer ","h.post(","h.put(","h.delete("):
        assert bad not in s
    assert '"provider_writes":0' in s
