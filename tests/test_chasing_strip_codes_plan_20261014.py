from pathlib import Path
import ast
def test_code_cleanup_plan_only():
 s=Path("scripts/ironman_jobs/chasing_strip_codes_plan_20261014.py").read_text()
 ast.parse(s)
 for v in ("PLAN=685173","OWNER=2116886","PERSON=6682479","len(patches)==172","BACKUP","CODE.search","PREWRITE_DRIFT_","PASS_ALL_172","_retry_on_401=False"):
  assert v in s
 assert '"/plans/v1/plans/{PLAN}/workouts/{wid}"' in s
 assert "calendarNote" in s
 assert "exerciseLibrary" not in s
 assert "athlete" not in s.lower() or "athlete calendars" in s.lower()
