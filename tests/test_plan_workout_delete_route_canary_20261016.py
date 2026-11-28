from pathlib import Path
import ast
def test_lab_delete_route_scope():
 s=Path("scripts/ironman_jobs/plan_workout_delete_route_canary_20261016.py").read_text()
 ast.parse(s)
 assert "P=684484" in s and "WID=3995256662" in s
 assert 'workoutTypeValueId")==100' in s
 assert '_request("DELETE"' in s
 assert "_retry_on_401=False" in s
 assert "PLAN_WORKOUT_DELETE_ROUTE_VERIFIED" in s
 assert "679801" not in s
