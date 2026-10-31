from pathlib import Path


def test_prefect_admin_keygen_is_local_only_and_non_repeating():
    text = Path("scripts/ironman_jobs/prefect_admin_keygen_20261016.py").read_text()
    assert '"/home/ironman/.ssh"' in text
    assert '"ed25519"' in text
    assert "PREFECT_ADMIN_KEY_ALREADY_EXISTS_REVIEW_BEFORE_RETRY" in text
    assert "TrainingPeaks" in text
    assert "ssh-keygen" in text
    assert "private_key" in text
    assert "read_text" in text
