import ast
from pathlib import Path
def test_fixed_scope():
 s=Path("scripts/ironman_jobs/beginner_rpe_w01_w05_20261016.py").read_text()
 ast.parse(s)
 assert "run_phase(1,5,15)" in s
 shared=Path("scripts/ironman_jobs/beginner_rpe_native_guarded_common_20261016.py").read_text()
 ast.parse(shared)
 assert "PLAN,OWNER" in shared
 assert "BACKUP_ALREADY_EXISTS_CHECK_PROVIDER_BEFORE_RETRY" in shared
 assert "UNRELATED_WORKOUT_CHANGED" in shared
 assert "POSTWRITE_NATIVE_BUILDER_DRIFT" in shared
 assert "calendar_notes_unchanged" in shared
