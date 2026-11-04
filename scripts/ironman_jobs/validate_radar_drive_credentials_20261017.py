"""Validate the dedicated IRONMAN Radar Google Drive service-account key.

Local-only validation. Does not call Google APIs and does not expose private-key data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED_PROJECT_ID = "publimage-varie"
EXPECTED_EMAIL_LOCALPART = "ironman-radar-drive-reader"


def validate_credentials(path: Path) -> dict:
    result = {
        "schema": "IRONMAN_RADAR_DRIVE_CREDENTIAL_VALIDATION_V1",
        "path": str(path),
        "valid": False,
        "project_id": None,
        "client_email": None,
        "private_key_present": False,
    }
    if not path.is_file():
        result["error"] = "CREDENTIAL_FILE_MISSING"
        return result
    mode = path.stat().st_mode & 0o777
    result["mode"] = oct(mode)
    if mode & 0o077:
        result["error"] = f"CREDENTIAL_FILE_PERMISSIONS_TOO_OPEN:{oct(mode)}"
        return result
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["error"] = f"CREDENTIAL_JSON_INVALID:{type(exc).__name__}"
        return result

    project_id = str(raw.get("project_id") or "")
    client_email = str(raw.get("client_email") or "")
    result["project_id"] = project_id
    result["client_email"] = client_email
    result["private_key_present"] = bool(raw.get("private_key"))

    if raw.get("type") != "service_account":
        result["error"] = "CREDENTIAL_TYPE_MISMATCH"
        return result
    if project_id != EXPECTED_PROJECT_ID:
        result["error"] = f"CREDENTIAL_PROJECT_MISMATCH:{project_id}"
        return result
    expected_email = f"{EXPECTED_EMAIL_LOCALPART}@{EXPECTED_PROJECT_ID}.iam.gserviceaccount.com"
    if client_email != expected_email:
        result["error"] = f"CREDENTIAL_EMAIL_MISMATCH:{client_email}"
        return result
    if not raw.get("private_key") or not raw.get("private_key_id"):
        result["error"] = "CREDENTIAL_PRIVATE_KEY_MISSING"
        return result
    if not raw.get("token_uri", "").startswith("https://oauth2.googleapis.com/"):
        result["error"] = "CREDENTIAL_TOKEN_URI_MISMATCH"
        return result

    result["valid"] = True
    result["error"] = None
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    result = validate_credentials(Path(args.path))
    print("RADAR_DRIVE_CREDENTIAL_VALIDATION")
    # Never print the key material.
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
