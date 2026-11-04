from pathlib import Path


CANARY = Path("scripts/ironman_jobs/coaching_radar_drive_live_canary_20261017.py").read_text()
INSTALLER = Path("scripts/ironman_jobs/prepare_radar_drive_reader_runtime_20261017.sh").read_text()


def test_canary_is_read_only_and_does_not_print_document_content():
    assert "DRIVE_READONLY_SCOPE" in CANARY
    assert '"drive_writes": 0' in CANARY
    assert '"trainingpeaks_writes": 0' in CANARY
    assert 'print(content)' not in CANARY
    assert "KB_CREDENTIALS_FILE_PERMISSIONS_TOO_OPEN" in CANARY


def test_installer_uses_isolated_runtime_and_pinned_google_auth():
    assert "/opt/ironman-prefect/drive-reader" in INSTALLER
    assert "google-auth[requests]==2.62.0" in INSTALLER
    assert "RADAR_DRIVE_READER_RUNTIME_PASS" in INSTALLER
    assert "git config --global safe.directory" not in INSTALLER
    assert "pip install" in INSTALLER
    assert "ironman-prefect-worker.service" in INSTALLER


def test_installer_does_not_restart_services_or_accept_credentials():
    assert "systemctl restart" not in INSTALLER
    assert "reboot" not in INSTALLER
    assert "credentials-file" not in INSTALLER
    assert "CREDENTIAL_DIR=/var/lib/ironman-prefect/credentials" in INSTALLER
