from pathlib import Path

P = Path("scripts/ironman_jobs/install_spaces_interactive_helper_20261017.py")

def test_helper_installer_is_secret_free_and_uses_hidden_prompts():
    text = P.read_text()
    assert "getpass.getpass" in text
    assert "secret_access_key" in text
    assert "input hidden" in text
    assert "os.replace" in text
    assert "0o600" in text
    assert "credential_values_handled=0" in text
    assert "DO801" not in text
