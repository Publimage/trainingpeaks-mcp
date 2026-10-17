from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/whole_training_plan_lifecycle_canary_20261017.py"
def test_guarded_whole_plan_lifecycle_canary():
 s=P.read_text(encoding="utf-8");ast.parse(s)
 assert 'SOURCE=684484' in s
 assert 'PROTECTED={679801,684602,685173}' in s
 assert 'DELETE_ROUTE="/plans/v1/plans/{plan_id}"' in s
 assert 'COPY_ROUTE="/plans/v1/commands/copyplan"' in s
 assert '_retry_on_401=False' in s
 assert '"POST",COPY_ROUTE' in s
 assert '"DELETE",DELETE_ROUTE.format(plan_id=pid)' in s
 assert 'FINAL_PLAN_INVENTORY_DRIFT' in s
 assert 'athlete_calendar_writes":0' in s
 assert 'never_blind_retry":True' in s
