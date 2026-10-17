from pathlib import Path
import importlib.util

P = Path("scripts/ironman_jobs/training_plan_planfolder_recursive_js_20261017.py")
spec = importlib.util.spec_from_file_location("recursive_tp_js", P)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

def test_get_only_contract():
    s = P.read_text()
    assert "client.get(" in s
    assert "client.post(" not in s
    assert "client.put(" not in s
    assert "client.delete(" not in s
    assert "/planfolder/" in s

def test_trusted_same_release_only():
    prefix = "/release-20261016-abc/"
    assert m.trusted("https://app.trainingpeaks.com/release-20261016-abc/a-123456.js", prefix)
    assert not m.trusted("https://evil.example/release-20261016-abc/a-123456.js", prefix)
    assert not m.trusted("https://app.trainingpeaks.com/release-other/a-123456.js", prefix)
