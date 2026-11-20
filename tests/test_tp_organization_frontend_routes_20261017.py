from pathlib import Path
import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ironman_jobs" / "tp_organization_frontend_routes_20261017.py"
spec = importlib.util.spec_from_file_location("tp_org_frontend_routes", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_public_get_only_discovery_contract():
    source = SCRIPT.read_text()
    assert "client.get(" in source
    assert "client.post(" not in source
    assert "client.put(" not in source
    assert "client.patch(" not in source
    assert "client.delete(" not in source


def test_host_allowlist():
    assert module.trusted("https://app.trainingpeaks.com/a.js")
    assert module.trusted("https://cdn.trainingpeaks.com/b.js")
    assert not module.trusted("https://evil.example.com/trainingpeaks.com.js")


def test_terms_cover_plan_and_library_organization():
    assert "plansWithAccess" in module.TERMS
    assert "planFolder" in module.TERMS
    assert "/plans/v1/" in module.TERMS
    assert "/exerciselibrary/v1/libraries/" in module.TERMS
