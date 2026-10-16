#!/usr/bin/env python3
"""Private, typed admin API for ironman-prefect-staging.

Binds only to the VPC interface, accepts only the TP droplet source address,
and exposes fixed operations. There is no arbitrary shell endpoint.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HOST = "10.114.0.3"
PORT = 8790
ALLOWED_SOURCE = "10.114.0.2"
HOSTNAME_REQUIRED = "ironman-prefect-staging"
REPO_URL = "https://github.com/Publimage/trainingpeaks-mcp.git"
STATE_DIR = Path("/var/lib/ironman-prefect/private-admin-api")
MAX_BODY = 32768
MAX_OUTPUT = 12000
HEX40 = re.compile(r"^[a-f0-9]{40}$")
DATE = re.compile(r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(argv: list[str], *, cwd: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env={
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "HOME": "/root",
        },
    )


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def status_payload() -> dict[str, Any]:
    server = run(["systemctl", "is-active", "ironman-prefect-server.service"], timeout=10)
    worker = run(["systemctl", "is-active", "ironman-prefect-worker.service"], timeout=10)
    timer = run(["systemctl", "is-active", "ironman-prefect-backup.timer"], timeout=10)
    return {
        "schema": "IRONMAN_PREFECT_ADMIN_STATUS_V1",
        "host": HOSTNAME_REQUIRED,
        "prefect_server": (server.stdout or server.stderr).strip(),
        "prefect_worker": (worker.stdout or worker.stderr).strip(),
        "backup_timer": (timer.stdout or timer.stderr).strip(),
        "checked_at_utc": utcnow(),
        "trainingpeaks_writes": 0,
    }


def deploy_radar(revision: str, as_of: str) -> dict[str, Any]:
    if not HEX40.fullmatch(revision):
        raise ValueError("REVISION_INVALID")
    if not DATE.fullmatch(as_of):
        raise ValueError("AS_OF_INVALID")

    fingerprint = f"coaching-radar-{revision}-{as_of}"
    receipt = STATE_DIR / f"{fingerprint}.json"
    if receipt.exists():
        previous = json.loads(receipt.read_text(encoding="utf-8"))
        return {**previous, "replayed": True}

    started = utcnow()
    atomic_write(receipt, {
        "schema": "IRONMAN_PREFECT_ADMIN_DEPLOY_V1",
        "operation": "deploy_coaching_radar",
        "revision": revision,
        "as_of": as_of,
        "state": "STARTED",
        "started_at_utc": started,
        "trainingpeaks_writes": 0,
    })

    result: dict[str, Any]
    try:
        with tempfile.TemporaryDirectory(prefix="ironman-prefect-admin-") as temp:
            repo = Path(temp) / "repo"
            steps = [
                run(["git", "init", "-q", str(repo)], timeout=20),
                run(["git", "-C", str(repo), "remote", "add", "origin", REPO_URL], timeout=10),
                run(["git", "-C", str(repo), "fetch", "-q", "--depth=1", "origin", revision], timeout=90),
                run(["git", "-C", str(repo), "checkout", "-q", "--detach", "FETCH_HEAD"], timeout=20),
            ]
            if any(step.returncode != 0 for step in steps):
                raise RuntimeError("GIT_PREPARE_FAILED")
            head = run(["git", "-C", str(repo), "rev-parse", "HEAD"], timeout=10)
            if head.returncode != 0 or head.stdout.strip() != revision:
                raise RuntimeError("PINNED_REVISION_MISMATCH")
            installer = repo / "scripts/ironman_jobs/install_coaching_radar_staging_20261016.sh"
            if not installer.is_file():
                raise RuntimeError("INSTALLER_NOT_FOUND")
            proc = run(["bash", str(installer), revision, as_of], cwd=str(repo), timeout=360)
            state = "COMPLETED" if proc.returncode == 0 else "FAILED"
            output = (proc.stdout + "\n" + proc.stderr)[-MAX_OUTPUT:]
            result = {
                "schema": "IRONMAN_PREFECT_ADMIN_DEPLOY_V1",
                "operation": "deploy_coaching_radar",
                "revision": revision,
                "as_of": as_of,
                "state": state,
                "exit_code": proc.returncode,
                "started_at_utc": started,
                "finished_at_utc": utcnow(),
                "output": output,
                "trainingpeaks_writes": 0,
                "replayed": False,
            }
    except Exception as exc:
        result = {
            "schema": "IRONMAN_PREFECT_ADMIN_DEPLOY_V1",
            "operation": "deploy_coaching_radar",
            "revision": revision,
            "as_of": as_of,
            "state": "FAILED",
            "exit_code": 99,
            "started_at_utc": started,
            "finished_at_utc": utcnow(),
            "output": f"{type(exc).__name__}:{exc}",
            "trainingpeaks_writes": 0,
            "replayed": False,
        }

    atomic_write(receipt, result)
    return result


class Handler(BaseHTTPRequestHandler):
    server_version = "IRONMANPrefectAdmin/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def allowed(self) -> bool:
        return str(self.client_address[0]) == ALLOWED_SOURCE

    def reply(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if not self.allowed():
            self.reply(403, {"error": "SOURCE_NOT_ALLOWED"})
            return
        if self.path == "/health":
            self.reply(200, {"status": "ok", "schema": "IRONMAN_PREFECT_PRIVATE_ADMIN_V1"})
            return
        if self.path == "/v1/status":
            self.reply(200, status_payload())
            return
        self.reply(404, {"error": "NOT_FOUND"})

    def do_POST(self) -> None:
        if not self.allowed():
            self.reply(403, {"error": "SOURCE_NOT_ALLOWED"})
            return
        if self.path != "/v1/deploy-coaching-radar":
            self.reply(404, {"error": "NOT_FOUND"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0 or length > MAX_BODY:
                raise ValueError("INVALID_BODY_SIZE")
            payload = json.loads(self.rfile.read(length))
            if set(payload) != {"revision", "as_of"}:
                raise ValueError("INVALID_FIELDS")
            result = deploy_radar(str(payload["revision"]), str(payload["as_of"]))
            self.reply(200 if result.get("state") == "COMPLETED" else 500, result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.reply(400, {"error": "INVALID_REQUEST", "message": str(exc)})
        except Exception:
            self.reply(500, {"error": "INTERNAL_ERROR"})


def main() -> int:
    if os.uname().nodename != HOSTNAME_REQUIRED:
        raise RuntimeError("WRONG_HOST")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
