from pathlib import Path
import ast

P=Path("scripts/ironman_jobs/chasing_w07_thu_steady_ftp_only_20261014.py")

def test_exact_scope():
 s=P.read_text()
 t=ast.parse(s)
 for token in ["PLAN=685173","OWNER=2116886","PERSON=6682479","WID=4000972961","DATE=\"2027-02-18\"","percentOfFtp","_ensure_structure_preview","PASS_ONE_IN_PLACE_VERIFIED","OTHER_WORKOUT_CHANGED","BACKUP_ALREADY_EXISTS_RECONCILE"]:
  assert token in s
 assert "exerciseLibrary" not in s
 assert "tp_update_workout" not in s
 assert '"/plans/v1/plans/{PLAN}/workouts/{WID}"' in s

def test_approved_shape_only():
 s=P.read_text()
 t=ast.parse(s)
 value=None
 for z in t.body:
  if isinstance(z,ast.Assign) and any(isinstance(n,ast.Name) and n.id=="EXPECTED" for n in z.targets):
   value=ast.literal_eval(z.value)
 assert value==( ("warmUp",900,(50,60)),("active",480,(80,85)),("rest",720,(55,65)),("active",2700,(60,70)),("coolDown",600,(45,55)) )
