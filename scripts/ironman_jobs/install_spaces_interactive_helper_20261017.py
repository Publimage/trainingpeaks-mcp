"""Install a local interactive credential helper for the IRONMAN Spaces uploader.

The installed helper prompts inside the Droplet console using getpass, validates
the pair against Spaces before writing it, and never prints credential values.
"""
from __future__ import annotations

import os
from pathlib import Path

BIN_DIR = Path("/home/ironman/bin")
HELPER = BIN_DIR / "ironman-spaces-setup"

HELPER_TEXT = r'''#!/usr/bin/env python3
from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

TARGET = Path("/home/ironman/.config/ironman/spaces-uploader.json")
EXPECTED = {
    "bucket": "ironman-assets",
    "region": "fra1",
    "public_host": "ironman-assets.fra1.digitaloceanspaces.com",
}
PROBE_KEY = "shared/__ironman_spaces_setup_probe_nonexistent__"

def signing_key(secret_key: str, date_stamp: str, region: str) -> bytes:
    k_date = hmac.new(("AWS4" + secret_key).encode(), date_stamp.encode(), hashlib.sha256).digest()
    k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()

def signed_headers(access_key: str, secret_key: str):
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    host = EXPECTED["public_host"]
    region = EXPECTED["region"]
    payload_sha = hashlib.sha256(b"").hexdigest()
    canonical_uri = "/" + quote(PROBE_KEY, safe="/-_.~")
    canonical_headers = f"host:{host}\nx-amz-content-sha256:{payload_sha}\nx-amz-date:{amz_date}\n"
    signed = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(["GET", canonical_uri, "", canonical_headers, signed, payload_sha])
    scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        scope,
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])
    sig = hmac.new(signing_key(secret_key, date_stamp, region), string_to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        "Host": host,
        "x-amz-content-sha256": payload_sha,
        "x-amz-date": amz_date,
        "Authorization": f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed}, Signature={sig}",
    }

def parse_code(body: bytes):
    try:
        root = ET.fromstring(body)
        return root.findtext("Code")
    except Exception:
        return None

def validate_pair(access_key: str, secret_key: str):
    if access_key == secret_key:
        return False, "ACCESS_KEY_EQUALS_SECRET"
    if not access_key or not secret_key:
        return False, "MISSING_VALUE"
    if any(ch.isspace() for ch in access_key) or any(ch.isspace() for ch in secret_key):
        return False, "WHITESPACE_PRESENT"
    url = f"https://{EXPECTED['public_host']}/{PROBE_KEY}"
    req = urllib.request.Request(url, method="GET", headers=signed_headers(access_key, secret_key))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = resp.status
            body = resp.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
    except Exception as exc:
        return False, f"NETWORK_{type(exc).__name__}"
    code = parse_code(body)
    if status == 404 and code in (None, "NoSuchKey"):
        return True, "AUTH_VERIFIED"
    if status == 403 and code:
        return False, code
    return False, f"UNEXPECTED_HTTP_{status}"

def main() -> int:
    access_key = getpass.getpass("Spaces access key ID (input hidden): ").strip()
    secret_key = getpass.getpass("Spaces secret access key (input hidden): ").strip()

    id_shape = {
        "length": len(access_key),
        "ascii": access_key.isascii(),
        "alnum": access_key.isalnum(),
        "starts_do": access_key.startswith("DO"),
    }
    ok, reason = validate_pair(access_key, secret_key)
    if not ok:
        print("SPACES_CREDENTIAL_SETUP_REJECTED")
        print(json.dumps({
            "reason": reason,
            "existing_config_preserved": TARGET.exists(),
            "access_key_id_shape": id_shape,
        }, sort_keys=True))
        return 2

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(TARGET.parent, 0o700)
    payload = {**EXPECTED, "access_key_id": access_key, "secret_access_key": secret_key}

    fd, tmp_name = tempfile.mkstemp(prefix=".spaces-uploader.", dir=TARGET.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, TARGET)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    loaded = json.loads(TARGET.read_text(encoding="utf-8"))
    mode = TARGET.stat().st_mode & 0o777
    structural_ok = (
        loaded.get("bucket") == EXPECTED["bucket"]
        and loaded.get("region") == EXPECTED["region"]
        and loaded.get("public_host") == EXPECTED["public_host"]
        and bool(loaded.get("access_key_id"))
        and bool(loaded.get("secret_access_key"))
        and mode == 0o600
    )
    print("SPACES_CREDENTIAL_SETUP_VERIFIED_PASS" if structural_ok else "SPACES_CREDENTIAL_SETUP_FAILED")
    print(json.dumps({
        "path": str(TARGET),
        "bucket": loaded.get("bucket"),
        "region": loaded.get("region"),
        "public_host": loaded.get("public_host"),
        "access_key_id_present": bool(loaded.get("access_key_id")),
        "secret_access_key_present": bool(loaded.get("secret_access_key")),
        "mode": oct(mode),
        "live_auth": "PASS",
    }, sort_keys=True))
    return 0 if structural_ok else 3

if __name__ == "__main__":
    raise SystemExit(main())
'''

def main() -> int:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    HELPER.write_text(HELPER_TEXT, encoding="utf-8")
    os.chmod(HELPER, 0o700)
    st = HELPER.stat()
    assert st.st_uid == os.geteuid()
    assert (st.st_mode & 0o777) == 0o700
    print("SPACES_INTERACTIVE_HELPER_INSTALL_PASS")
    print(f"path={HELPER}")
    print("live_validation_before_write=true")
    print("credential_values_handled=0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
