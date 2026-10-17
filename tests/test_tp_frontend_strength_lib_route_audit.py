"""Offline checks for public TrainingPeaks frontend routes inspector."""
import importlib.util
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ironman_jobs"/"tp_frontend_strength_lib_route_audit.py"
spec=importlib.util.spec_from_file_location("tp_frontend_audit",SCRIPT)
assert spec and spec.loader
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_allowed_host_guard():
    assert module.trusted("https://app.trainingpeaks.com/a.js")
    assert module.trusted("https://cdn.trainingpeaks.com/b.js")
    assert not module.trusted("https://evil.example.com/trainingpeaks.com.js")

def test_snippet_matching():
    s="let x={url:'/exerciselibrary/v1/libraries/55/items'}; function StrengthWorkout(){}"
    result=module.snippets(s)
    assert any("exerciselibrary" in row for row in result)
