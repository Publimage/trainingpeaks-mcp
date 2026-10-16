#!/usr/bin/env python3
"""IRONMAN Prefect private admin pull agent.

No inbound port and no arbitrary shell. The agent polls one public GitHub JSON
manifest, accepts only fixed allowlisted operations, keeps a local one-shot
receipt, and posts a bounded result to the TP droplet over the private VPC.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_URL = (
    "https://raw.githubusercontent.com/Publimage/trainingpeaks-mcp/"
    "lab/ironman-prefect-20261015/data/prefect_admin_command.json"
)
RESULT_URL = "http://10.114.0.2:8787/v1/admin-result"
STATE_DIR = Path("/var/lib/ironman-prefect/admin-agent")
REPO_URL = "https://github.com/Publimage/trainingpeaks-mcp.git"
HOSTNAME_REQUIRED = "ironman-prefect-staging"
ALLOWED_OPERATIONS = {"status", "deploy_coaching_radar"}
HEX40 = re.compile(r"^[a-f0-9]{40}$")
JOB_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{7,95}$")
DATE = re.compile(r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$")
MAX_OUTPUT = 12000


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def fetch_json(url: str, timeout: int = 15) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "IRONMAN-Prefect-Admin/1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP_{response.status}")
        raw = response.read(128 * 1024)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("MANIFEST_NOT_OBJECT")
    return data


def validate_manifest(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema") != "IRONMAN_PREFECT_ADMIN_COMMAND_V1":
        raise RuntimeError("MANIFEST_SCHEMA_INVALID")
    job_id = str(data.get("job_id") or "")
    operation = str(data.get("operation") or "")
    if not JOB_ID.fullmatch(job_id):
        raise RuntimeError("JOB_ID_INVALID")
    if operation not in ALLOWED_OPERATIONS:
        raise RuntimeError("OPERATION_NOT_ALLOWED")
    params = data.get("params") or {}
    if not isinstance(params, dict):
        raise RuntimeError("PARAMS_INVALID")

    if operation == "status":
        if params:
            raise RuntimeError("STATUS_TAKES_NO_PARAMS")
    elif operation == "deploy_coaching_radar":
        revision = str(params.get("revision") or "")
        as_of = str(params.get("as_of") or "")
        if not HEX40.fullmatch(revision):
            raise RuntimeError("REVISION_INVALID")
        if not DATE.fullmatch(as_of):
            raise RuntimeError("AS_OF_INVALID")
        if set(params) != {"revision", "as_of"}:
            raise RuntimeError("DEPLOY_PARAMS_INVALID")

    return {"job_id": job_id, "operation": operation, "params": params}


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


def status_details() -> tuple[int, str, dict[str, Any]]:
    server = run(["systemctl", "is-active", "ironman-prefect-server.service"], timeout=10)
    worker = run(["systemctl", "is-active", "ironman-prefect-worker.service"], timeout=10)
    health = ""
    bridge = ""
    try:
        health = urllib.request.urlopen("http://127.0.0.1:4200/api/health", timeout=5).read().decode()
    except Exception as exc:
        health = type(exc).__name__
    try:
        bridge = urllib.request.urlopen("http://10.114.0.2:8787/health", timeout=5).read().decode()
    except Exception as exc:
        bridge = type(exc).__name__
    details = {
        "prefect_server": server.stdout.strip() or server.stderr.strip(),
        "prefect_worker": worker.stdout.strip() or worker.stderr.strip(),
        "prefect_health": health[:500],
        "private_bridge_health": bridge[:500],
    }
    ok = server.returncode == 0 and worker.returncode == 0 and '"status":"ok"' in bridge.replace(" ", "")
    return (0 if ok else 1, json.dumps(details, ensure_ascii=False), details)


def deploy_coaching_radar(params: dict[str, Any]) -> tuple[int, str, dict[str, Any]]:
    revision = str(params["revision"])
    as_of = str(params["as_of"])
    with tempfile.TemporaryDirectory(prefix="ironman-admin-") as temp:
        repo = Path(temp) / "repo"
        init = run(["git", "init", "-q", str(repo)], timeout=20)
        if init.returncode != 0:
            return init.returncode, init.stderr, {"stage": "git_init"}
        remote = run(["git", "-C", str(repo), "remote", "add", "origin", REPO_URL], timeout=10)
        if remote.returncode != 0:
            return remote.returncode, remote.stderr, {"stage": "git_remote"}
        fetch = run(
            ["git", "-C", str(repo), "fetch", "-q", "--depth=1", "origin", revision],
            timeout=90,
        )
        if fetch.returncode != 0:
            return fetch.returncode, fetch.stderr, {"stage": "git_fetch"}
        checkout = run(["git", "-C", str(repo), "checkout", "-q", "--detach", "FETCH_HEAD"], timeout=20)
        if checkout.returncode != 0:
            return checkout.returncode, checkout.stderr, {"stage": "git_checkout"}
        head = run(["git", "-C", str(repo), "rev-parse", "HEAD"], timeout=10)
        if head.stdout.strip() != revision:
            return 2, "PINNED_REVISION_MISMATCH", {"stage": "revision_check"}
        installer = repo / "scripts/ironman_jobs/install_coaching_radar_staging_20261016.sh"
        if not installer.is_file():
            return 2, "INSTALLER_NOT_FOUND", {"stage": "installer_check"}
        proc = run(["bash", str(installer), revision, as_of], cwd=str(repo), timeout=300)
        details = {"stage": "installer", "revision": revision, "as_of": as_of}
        return proc.returncode, (proc.stdout + "\n" + proc.stderr)[-MAX_OUTPUT:], details


def post_result(payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        RESULT_URL,
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"RESULT_HTTP_{response.status}")
        ack = json.loads(response.read().decode("utf-8"))
    if not ack.get("stored") or ack.get("trainingpeaks_writes") != 0:
        raise RuntimeError("RESULT_ACK_INVALID")


def main() -> int:
    if os.uname().nodename != HOSTNAME_REQUIRED:
        raise RuntimeError("WRONG_HOST")

    command = validate_manifest(fetch_json(MANIFEST_URL))
    job_id = command["job_id"]
    receipt = STATE_DIR / "receipt.json"
    if receipt.exists():
        previous = json.loads(receipt.read_text(encoding="utf-8"))
        if previous.get("job_id") == job_id:
            return 0

    started = utcnow()
    atomic_write(receipt, {
        "job_id": job_id,
        "operation": command["operation"],
        "state": "STARTED",
        "started_at_utc": started,
    })

    exit_code = 1
    output = ""
    details: dict[str, Any] = {}
    try:
        if command["operation"] == "status":
            exit_code, output, details = status_details()
        elif command["operation"] == "deploy_coaching_radar":
            exit_code, output, details = deploy_coaching_radar(command["params"])
        state = "COMPLETED" if exit_code == 0 else "FAILED"
    except Exception as exc:
        state = "FAILED"
        output = f"{type(exc).__name__}:{exc}"
        details = {"stage": "agent_exception"}

    result = {
        "schema": "IRONMAN_PREFECT_ADMIN_RESULT_V1",
        "job_id": job_id,
        "operation": command["operation"],
        "state": state,
        "source_host": HOSTNAME_REQUIRED,
        "started_at_utc": started,
        "finished_at_utc": utcnow(),
        "exit_code": exit_code,
        "revision": command["params"].get("revision"),
        "details": details,
        "output": output[-MAX_OUTPUT:],
        "trainingpeaks_writes": 0,
    }
    atomic_write(STATE_DIR / f"{job_id}.json", result)
    atomic_write(receipt, {
        "job_id": job_id,
        "operation": command["operation"],
        "state": state,
        "finished_at_utc": result["finished_at_utc"],
    })
    post_result(result)
    return 0 if state == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
