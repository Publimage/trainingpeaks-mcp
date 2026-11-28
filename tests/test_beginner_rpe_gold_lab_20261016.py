import ast
from pathlib import Path
def test_lab_canary_scoped_and_guarded():
 s=Path("scripts/ironman_jobs/beginner_rpe_gold_lab_20261016.py").read_text()
 ast.parse(s)
 assert "P=684206;WID=3994992835" in s
 assert 'isPublic") is False' in s
 assert "len(before)==6" in s and 'BACKUP.exists()' in s
 assert 'metric_before' in s and "polyline" in s
 assert "/plans/v1/plans/{P}/workouts/{WID}" in s
 assert "679801" in s and "Never touches Beginner public" in s
 assert "PUT" in s
