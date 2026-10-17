from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/training_plan_folder_frontend_routes_readonly.py"

def test_public_readonly_route_probe():
    s=P.read_text(encoding="utf-8")
    ast.parse(s)
    assert "https://app.trainingpeaks.com/" in s
    assert "plansWithAccess" in s
    assert "planFolder" in s
    assert "/plans/v1/" in s
    assert "httpx.AsyncClient" in s
    for bad in ("TPClient","Authorization","Bearer ","post(","put(","delete(","patch("):
        assert bad not in s
    assert '"provider_writes":0' in s
