from pathlib import Path

P=Path("scripts/ironman_jobs/digitalocean_api_auth_inventory_20261017.py")

def test_diagnostic_never_prints_token_values():
    t=P.read_text()
    assert "DIGITALOCEAN_API_AUTH_INVENTORY" in t
    assert "os.environ.get(name)" in t
    assert "print(os.environ" not in t
    assert "DIGITALOCEAN_TOKEN" in t
