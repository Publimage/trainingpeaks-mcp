"""Install a local interactive credential helper for the IRONMAN Spaces uploader.

The installed helper prompts inside the Droplet console using getpass so the
Spaces secret never appears in shell history, GitHub, Google Drive, or chat.
This job itself handles no credential value.
"""
from __future__ import annotations

import os
from pathlib import Path

BIN_DIR = Path("/home/ironman/bin")
HELPER = BIN_DIR / "ironman-spaces-setup"

HELPER_TEXT = r'''#!/usr/bin/env python3
from __future__ import annotations

import getpass
import json
import os
import tempfile
from pathlib import Path

TARGET = Path("/home/ironman/.config/ironman/spaces-uploader.json")
EXPECTED = {
    "bucket": "ironman-assets",
    "region": "fra1",
    "public_host": "ironman-assets.fra1.digitaloceanspaces.com",
}

def main() -> int:
    access_key = getpass.getpass("Spaces access key ID (input hidden): ").strip()
    secret_key = getpass.getpass("Spaces secret access key (input hidden): ").strip()
    if not access_key or not secret_key:
        print("ERROR: both credential values are required.")
        return 2

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(TARGET.parent, 0o700)

    payload = {
        **EXPECTED,
        "access_key_id": access_key,
        "secret_access_key": secret_key,
    }

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

    # Non-secret verification only.
    loaded = json.loads(TARGET.read_text(encoding="utf-8"))
    fields = sorted(loaded)
    ok = (
        loaded.get("bucket") == EXPECTED["bucket"]
        and loaded.get("region") == EXPECTED["region"]
        and loaded.get("public_host") == EXPECTED["public_host"]
        and bool(loaded.get("access_key_id"))
        and bool(loaded.get("secret_access_key"))
        and (TARGET.stat().st_mode & 0o777) == 0o600
    )
    print("SPACES_CREDENTIAL_SETUP_PASS" if ok else "SPACES_CREDENTIAL_SETUP_FAILED")
    print(json.dumps({
        "path": str(TARGET),
        "fields": fields,
        "bucket": loaded.get("bucket"),
        "region": loaded.get("region"),
        "public_host": loaded.get("public_host"),
        "access_key_id_present": bool(loaded.get("access_key_id")),
        "secret_access_key_present": bool(loaded.get("secret_access_key")),
        "mode": oct(TARGET.stat().st_mode & 0o777),
    }, sort_keys=True))
    return 0 if ok else 3

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
    print("credential_values_handled=0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
