"""Create the dedicated SSH key used only for TP-droplet -> Prefect private admin channel.

This changes only local filesystem state on ironman-tp-mcp. It never contacts
TrainingPeaks and never exposes the private key. Re-running after a successful
creation is intentionally refused so key identity remains stable.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SSH_DIR = Path("/home/ironman/.ssh")
KEY = SSH_DIR / "ironman_prefect_admin_ed25519"
PUB = KEY.with_suffix(KEY.suffix + ".pub")


def main() -> int:
    SSH_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SSH_DIR, 0o700)

    if KEY.exists() or PUB.exists():
        raise RuntimeError("PREFECT_ADMIN_KEY_ALREADY_EXISTS_REVIEW_BEFORE_RETRY")

    subprocess.run(
        [
            "ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            "ironman-tp-mcp-to-prefect-staging",
            "-f",
            str(KEY),
        ],
        check=True,
        timeout=30,
    )
    os.chmod(KEY, 0o600)
    os.chmod(PUB, 0o644)

    public_key = PUB.read_text(encoding="utf-8").strip()
    if not public_key.startswith("ssh-ed25519 "):
        raise RuntimeError("PUBLIC_KEY_FORMAT_INVALID")

    fp = subprocess.run(
        ["ssh-keygen", "-lf", str(PUB), "-E", "sha256"],
        check=True,
        text=True,
        capture_output=True,
        timeout=10,
    ).stdout.strip()

    print("PREFECT_ADMIN_KEY_CREATED")
    print(json.dumps({
        "private_key_path": str(KEY),
        "public_key": public_key,
        "fingerprint": fp,
        "trainingpeaks_writes": 0,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
