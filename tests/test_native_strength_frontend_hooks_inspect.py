"""Static search behavior only. Never calls network during tests."""
import importlib.util
from pathlib import Path
FILE=Path(__file__).resolve().parents[1]/"scripts"/"ironman_jobs"/"native_strength_frontend_hooks_inspect.py"
spec=importlib.util.spec_from_file_location("frontendhooks",FILE)
assert spec and spec.loader
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
def test_search_windows():
    hits=module.spans("let A; onAddWorkoutToLibrary(foo); var K;", "onAddWorkoutToLibrary")
    assert len(hits)==1
    assert "onAddWorkoutToLibrary" in hits[0]["context"]
