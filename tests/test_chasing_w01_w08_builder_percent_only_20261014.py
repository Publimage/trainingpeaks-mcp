from pathlib import Path
import ast
def test_scope_and_percentages():
 s=Path("scripts/ironman_jobs/chasing_w01_w08_builder_percent_only_20261014.py").read_text()
 ast.parse(s)
 for x in ('P=685173','OWNER=2116886','PERSON=6682479','len(pool)==55','35<=len(patches)<=47','percentOfFtp','percentOfThresholdPace','_ensure_structure_preview','EXCEPT','"PUT",f"/plans/v1/plans/{P}/workouts/{wid}"','OTHER_WORKOUT_CHANGED_'):
  assert x in s
 for x in ('4000490168','4000490118','4000954256','4000591505','4000972961','4000973064'):
  assert x in s
 assert 'exerciseLibrary' not in s
 assert 'tp_update_workout' not in s
