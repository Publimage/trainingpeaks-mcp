from pathlib import Path
import ast
import re

SRC=Path("scripts/ironman_jobs/chasing_only_rename_rpe_titles_20261014.py")
def get_constants():
 root=ast.parse(SRC.read_text())
 return {node.targets[0].id:ast.literal_eval(node.value)
         for node in root.body
         if isinstance(node,ast.Assign) and len(node.targets)==1
         and isinstance(node.targets[0],ast.Name)
         and node.targets[0].id in ("ALLOWED","STEADY","STEADY_NEW","PLAN","OWNER","PERSON")}
def test_exact_product_scope():
 s=SRC.read_text()
 ast.parse(s)
 c=get_constants()
 assert c["PLAN"]==685173 and c["OWNER"]==2116886 and c["PERSON"]==6682479
 assert len(c["ALLOWED"])==len(set(c["ALLOWED"]))==30
 assert "RPE" not in c["STEADY_NEW"]
 for phrase in ("len(found)==42","sum(w[\"workoutTypeValueId\"]==2 for w in found)==27",
                "sum(w[\"workoutTypeValueId\"]==3 for w in found)==15",
                "other_207_workouts_unchanged","FINAL_WORKOUT_FIELDS_DRIFT",
                "BACKUP","swim_titles_unchanged"):
  assert phrase in s
 assert "/plans/v1/plans/{PLAN}/workouts/{wid}" in s
 assert "exerciseLibrary/" not in s
 assert "tp_update_workout(" not in s
def test_titles_canonical():
 c=get_constants()
 r=re.compile(r"(?:,\s*guida\s+RPE\s*\d+(?:\s*[-–]\s*\d+)?|,\s*RPE\s*\d+(?:\s*[-–]\s*\d+)?|\s+RPE\s*\d+(?:\s*[-–]\s*\d+)?)$",re.I)
 for title in c["ALLOWED"]:
  result=c["STEADY_NEW"] if title==c["STEADY"] else r.sub("",title)
  assert result!=title
  assert "RPE" not in result
  assert result.count("|")==1
  assert len(result.split("|")[0].strip())>0 and len(result.split("|")[1].strip())>0
