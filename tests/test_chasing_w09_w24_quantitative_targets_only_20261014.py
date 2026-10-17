from pathlib import Path
import ast

SRC=Path("scripts/ironman_jobs/chasing_w09_w24_quantitative_targets_only_20261014.py")
def test_guarded_scope():
 s=SRC.read_text(); tree=ast.parse(s)
 for token in ('P=685173','OWNER=2116886','PERSON=6682479',
     'len(rpe)==106','len(candidates)==94','len(candidates)==95','W21_RACE_ID=4001081215',
     'PAS'+'S_95_QUANTITATIVE_DELTA_ONLY','PACE_PLUS_EXPLICIT_REQUIRES_SOURCE_REFERENCE',
     'pct' if False else 'percentOfFtp','percentOfThresholdPace','_ensure_structure_preview',
     'PREWRITE_DRIFT_','POSTWRITE_NOT_VERIFIED_','UNRELATED_WORKOUT_MODIFIED_',
     'W01_W08_preserved','len(rows)==249','RUN_HOLDS'):
  assert token in s, token
 assert '"/plans/v1/plans/{P}/workouts/{wid}"' in s
 assert "exerciseLibrary/" not in s and "tp_update_workout" not in s

def test_exact_guarded_run_holds():
 tree=ast.parse(SRC.read_text())
 v=next(ast.literal_eval(x.value) for x in tree.body if isinstance(x,ast.Assign)
  and any(isinstance(n,ast.Name) and n.id=="RUN_HOLDS" for n in x.targets))
 assert len(v)==12
 assert 4001059176 in v and 4001076980 in v and 4001081245 in v
 assert {4001089853,4001089902,4001089934}.issubset(v)
