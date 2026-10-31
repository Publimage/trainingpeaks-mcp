from pathlib import Path
import ast,importlib.util

SRC=Path("scripts/ironman_jobs/chasing_paceplus_nine_20261014.py")
def test_guarded_plan_scope_and_static_delta():
 s=SRC.read_text(encoding="utf-8")
 tree=ast.parse(s)
 for term in ["P=685173","OWNER=2116886","PERSON=6682479",
              "NINE_PACEPLUS_PASS","GOLDEN_FIRST_PASS","BACKUP",
              "PREWRITE_DRIFT_","PUT_NOT_VERIFIED_",
              "UNRELATED_WORKOUT_DRIFT_","percentOfFtp",
              "Ironman Pace+","Ironman Pace",
              "PREFLIGHT_PASS","_ensure_structure_preview"]:
  assert term in s,term
 assert s.count('c._request("PUT"')==1
 assert "exerciseLibrary/" not in s and "tp_update_workout" not in s
 assert "publish" not in s.lower()
def test_ids_durations_repetition_splits():
 tree=ast.parse(SRC.read_text(encoding="utf-8"))
 table=next(ast.literal_eval(n.value) for n in tree.body
  if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=="SETS" for x in n.targets))
 assert set(table)=={4001050288,4001053067,4001058948,4001059223,4001062280,
  4001065433,4001071953,4001072083,4001074506}
 for wid,(wk,wd,reps,orig,pace,plus,rest,lead,finish,easy) in table.items():
  assert 10<=wk<=18 and wd in range(7)
  assert orig==pace+plus and plus>0 and pace>0
  assert rest>=8 and lead>0 and easy>0
 assert table[4001059223][4:6]==(27,8)
 assert table[4001072083][4:6]==(27,8)
