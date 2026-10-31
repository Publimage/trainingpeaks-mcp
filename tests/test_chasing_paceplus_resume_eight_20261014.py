import ast
from pathlib import Path
SRC=Path("scripts/ironman_jobs/chasing_paceplus_resume_eight_20261014.py")
def test_resume_guards():
 s=SRC.read_text()
 ast.parse(s)
 for k in ["FIRST=4001050288","len(IDS)==8","BACKUP.exists()","golden_w10",
           "UNEXPECTED_LIVE_DRIFT_","NEIGHBOR_DRIFT_","NINE_PACEPLUS_VERIFIED",
           "FINAL_NEIGHBOR_DRIFT_","PUT_NOT_VERIFIED_","isPublic"]:
  assert k in s,k
 assert s.count('c._request("PUT"')==1
 assert "/exerciselibrary/" not in s
 assert "tp_update_workout" not in s
