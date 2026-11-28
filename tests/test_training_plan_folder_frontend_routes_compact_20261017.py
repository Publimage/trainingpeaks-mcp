from pathlib import Path
import importlib.util
SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ironman_jobs"/"training_plan_folder_frontend_routes_compact_20261017.py"
spec=importlib.util.spec_from_file_location("plan_folder_frontend",SCRIPT)
assert spec and spec.loader
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_read_only():
    s=SCRIPT.read_text()
    assert "h.get(" in s
    assert "h.post(" not in s and "h.put(" not in s and "h.delete(" not in s and "h.patch(" not in s

def test_route_extractor():
    src='x="/plans/v1/commands/movePlanToFolder"; y="/plans/v1/folders"; z="/fitness/v6/foo"'
    routes=m.route_literals(src)
    assert "/plans/v1/commands/movePlanToFolder" in routes
    assert "/plans/v1/folders" in routes
    assert not any("/fitness/" in x for x in routes)
