from pathlib import Path
import ast

def test_w09_thu_chasing_single_instance_builder_only():
 src=Path("scripts/ironman_jobs/chasing_w09_thu_tempo_ftp_only_20261014.py").read_text()
 ast.parse(src)
 for token in ("PLAN=685173","OWNER=2116886","PERSON=6682479","WID=4001048439","TECH_DATE=\"2027-03-04\"","percentOfFtp","_ensure_structure_preview","TARGET_DIFF_NOT_EXACT","OTHER_W09_CHANGED","PASS_VERIFIED_W09_THU_FTP_ONLY"):
  assert token in src
 assert "tp_update_workout" not in src and "exerciseLibrary" not in src
 assert '"/plans/v1/plans/{PLAN}/workouts/{WID}"' in src
 tree=ast.parse(src)
 expected=next(ast.literal_eval(node.value) for node in tree.body
  if isinstance(node,ast.Assign) and any(isinstance(v,ast.Name) and v.id=="TARGETS" for v in node.targets))
 assert expected==( ("warmUp",900,50,60),("active",600,80,85),("rest",900,55,65),("active",1800,60,70),("coolDown",600,45,55))
