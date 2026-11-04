import json
from pathlib import Path

from scripts.ironman_jobs.validate_radar_drive_credentials_20261017 import validate_credentials


def _write(path: Path, *, project="publimage-varie", email="ironman-radar-drive-reader@publimage-varie.iam.gserviceaccount.com"):
    path.write_text(json.dumps({
        "type": "service_account",
        "project_id": project,
        "private_key_id": "key-id",
        "private_key": "-----BEGIN PRIVATE KEY-----\\nTEST\\n-----END PRIVATE KEY-----\\n",
        "client_email": email,
        "token_uri": "https://oauth2.googleapis.com/token"
    }))
    path.chmod(0o600)


def test_valid_dedicated_key(tmp_path):
    p=tmp_path/"key.json"; _write(p)
    out=validate_credentials(p)
    assert out["valid"] is True
    assert out["project_id"]=="publimage-varie"
    assert out["private_key_present"] is True


def test_rejects_wrong_project(tmp_path):
    p=tmp_path/"key.json"; _write(p, project="client-project")
    out=validate_credentials(p)
    assert out["valid"] is False
    assert out["error"].startswith("CREDENTIAL_PROJECT_MISMATCH")


def test_rejects_wrong_service_account(tmp_path):
    p=tmp_path/"key.json"; _write(p, email="other@publimage-varie.iam.gserviceaccount.com")
    out=validate_credentials(p)
    assert out["valid"] is False
    assert out["error"].startswith("CREDENTIAL_EMAIL_MISMATCH")


def test_rejects_open_permissions(tmp_path):
    p=tmp_path/"key.json"; _write(p); p.chmod(0o644)
    out=validate_credentials(p)
    assert out["valid"] is False
    assert out["error"].startswith("CREDENTIAL_FILE_PERMISSIONS_TOO_OPEN")


def test_missing_file(tmp_path):
    out=validate_credentials(tmp_path/"missing.json")
    assert out["valid"] is False
    assert out["error"]=="CREDENTIAL_FILE_MISSING"
