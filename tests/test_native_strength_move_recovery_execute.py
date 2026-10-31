from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/native_strength_move_recovery_execute.py"
def test_exact_recovery_scope():
 s=P.read_text();ast.parse(s)
 assert "SOURCE=3890637" in s and "TEMP=3902999" in s and "ITEM=330612" in s
 assert "/rx/activity/v1/libraryContent/workoutLibrary/save" in s
 assert "RESTORED_BLOCKS_DRIFT" in s
 assert "_retry_on_401=False" in s
 assert "/fitness/" not in s and "/plans/" not in s
