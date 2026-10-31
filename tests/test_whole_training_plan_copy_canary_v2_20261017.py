from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/whole_training_plan_copy_canary_v2_20261017.py"
def test_whole_plan_copy_canary_v2():
 s=P.read_text(encoding="utf-8");ast.parse(s)
 assert 'SOURCE=684484' in s
 assert 'PROTECTED={679801,684602,685173}' in s
 assert 'COPY_ROUTE="/plans/v1/commands/copyplan"' in s
 assert 'DELETE_ROUTE="/plans/v1/plans/{plan_id}"' in s
 assert 'planCopyStatus' in s
 assert '_retry_on_401=False' in s
 assert 'COPY_NOTES_DRIFT' in s
 assert 'FINAL_INVENTORY_DRIFT' in s
 assert 'never_blind_retry":True' in s
