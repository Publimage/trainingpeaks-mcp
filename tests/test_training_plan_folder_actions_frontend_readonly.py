from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/training_plan_folder_actions_frontend_readonly.py"
def test_public_only():
    s=P.read_text();ast.parse(s)
    assert "modules-8af7f7d8.js" in s
    assert "MOVE_PLANS_BETWEEN_FOLDERS" in s
    assert "CREATE_FOLDER" in s
    for bad in ("TPClient","Authorization","Bearer ","h.post(","h.put(","h.delete("):
        assert bad not in s
    assert '"provider_writes":0' in s
