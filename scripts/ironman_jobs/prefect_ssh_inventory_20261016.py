"""Read-only inventory for an existing TP-droplet -> Prefect SSH path.

Never prints private key material. It reports only filenames, modes, public-key
fingerprints and whether a matching private file exists, plus TCP reachability
to Prefect's private SSH port.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

SSH_DIR = Path("/home/ironman/.ssh")
TARGET = ("10.114.0.3", 22)


def _fingerprint(pub: Path) -> str | None:
    try:
        return subprocess.run(
            ["ssh-keygen", "-lf", str(pub), "-E", "sha256"],
            check=True,
            text=True,
            capture_output=True,
            timeout=5,
        ).stdout.strip()
    except Exception:
        return None


def main() -> int:
    entries = []
    if SSH_DIR.exists():
        for path in sorted(SSH_DIR.iterdir()):
            if path.is_symlink():
                continue
            mode = oct(path.stat().st_mode & 0o777)
            item = {"name": path.name, "mode": mode, "size": path.stat().st_size}
            if path.suffix == ".pub":
                item["fingerprint"] = _fingerprint(path)
                item["matching_private_exists"] = path.with_suffix("").is_file()
            else:
                item["private_candidate"] = (
                    path.is_file()
                    and path.name not in {"authorized_keys", "known_hosts", "config"}
                    and not path.name.endswith(".pub")
                )
            entries.append(item)

    reachable = False
    error = None
    try:
        with socket.create_connection(TARGET, timeout=3):
            reachable = True
    except OSError as exc:
        error = type(exc).__name__

    print("PREFECT_SSH_PATH_INVENTORY")
    print(json.dumps({
        "ssh_dir_exists": SSH_DIR.exists(),
        "entries": entries,
        "prefect_private_ip": TARGET[0],
        "prefect_ssh_port": TARGET[1],
        "tcp_reachable": reachable,
        "tcp_error": error,
        "trainingpeaks_writes": 0,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
