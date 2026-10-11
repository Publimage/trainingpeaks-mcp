"""IRONMAN goal-to-outcome task bridge for the existing cloud MCP.

One-time bootstrap is required to register this MCP tool. Later jobs are
version-pinned GitHub scripts selected by a typed, repository-owned registry.
Never accepts shell commands or arbitrary URLs/paths from the MCP caller.
Use an unprivileged Linux account, GitHub branch protection and reviewed commits.

Trust boundary: anybody who can push to the trusted branch can publish job code
that runs as the Linux MCP user. Only grant trusted maintainers write access.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from tp_mcp.client import TPClient
from tp_mcp.client.context import athlete_override

OWNER = 2116886
REPO = Path("/home/ironman/trainingpeaks-mcp")
VENV_PYTHON = Path("/home/ironman/tp-mcp-venv/bin/python")
BRANCH = "feat/mcp-test-training-plan-lab"
REGISTRY_PATH = Path("data/ironman_operator_jobs.json")
STATE_DIR = Path("/home/ironman/.local/state/ironman-operator")
HEX40 = re.compile(r"^[a-f0-9]{40}$")
SLUG = re.compile(r"^[a-z][a-z0-9_]{2,55}$")
ORIGIN = re.compile(r"^(?:https://github\.com/|git@github\.com:)Publimage/trainingpeaks-mcp(?:\.git)?$")
MAX_STDOUT = 14000
READ_ONLY = "READ_ONLY"
GUARDED_WRITE = "GUARDED_WRITE"


class BridgeStop(Exception):
    pass


def _run(*argv: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    env = {
        key: value for key, value in os.environ.items()
        if key in {"HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "XDG_CONFIG_HOME"}
    }
    env["HOME"] = str(REPO.parent)
    env["PYTHONPATH"] = str(REPO / "src")
    try:
        return subprocess.run(
            list(argv), cwd=REPO, env=env, text=True, capture_output=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeStop("Job subprocess exceeded timeout; inspect provider readback before repeating.") from exc
    except OSError as exc:
        raise BridgeStop("Job subprocess unavailable; no retry performed.") from exc


def _require_ok(r: subprocess.CompletedProcess[str], stage: str) -> str:
    if r.returncode != 0:
        raise BridgeStop(f"{stage} failed (exit={r.returncode}). No publish/retry.")
    return r.stdout.strip()


def _registry() -> dict[str, Any]:
    try:
        data = json.loads((REPO / REGISTRY_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BridgeStop("Approved job registry missing or invalid.") from exc
    if data.get("schema") != "IRONMAN_OPERATOR_JOBS_V1":
        raise BridgeStop("Unapproved registry schema.")
    entries = data.get("jobs")
    if not isinstance(entries, list) or not entries:
        raise BridgeStop("Empty approved job registry.")
    return {x["name"]: x for x in entries if isinstance(x, dict) and "name" in x}


def _check_job(job: str, operation: str, ack_scope: str | None) -> dict[str, Any]:
    if not SLUG.fullmatch(job):
        raise BridgeStop("Invalid job name.")
    spec = _registry().get(job)
    if spec is None:
        raise BridgeStop("Job not approved in repository registry.")
    path = spec.get("script")
    if (not isinstance(path, str) or not path.startswith("scripts/ironman_jobs/")
        or not path.endswith(".py") or ".." in Path(path).parts):
        raise BridgeStop("Unsafe job script path.")
    script = (REPO / path).resolve()
    if REPO.resolve() not in script.parents or not script.is_file():
        raise BridgeStop("Job script missing or outside trusted repo.")
    kind = spec.get("mode")
    if kind not in {READ_ONLY, GUARDED_WRITE}:
        raise BridgeStop("Unsafe job mode.")
    scope = spec.get("scope")
    if not isinstance(scope, str) or len(scope) < 8:
        raise BridgeStop("Invalid job scope.")
    if kind == GUARDED_WRITE and operation == "execute" and ack_scope != scope:
        raise BridgeStop("Protected write requires exact explicit scope acknowledgement.")
    if kind == READ_ONLY and ack_scope:
        raise BridgeStop("Read-only jobs do not accept write acknowledgement.")
    tests = spec.get("test")
    if (not isinstance(tests, str) or not tests.startswith("tests/test_")
        or not tests.endswith(".py") or ".." in Path(tests).parts
        or not (REPO / tests).resolve().is_file()):
        raise BridgeStop("Approved test path unavailable.")
    if spec.get("owner_id") != OWNER:
        raise BridgeStop("Wrong owner in job registry.")
    return spec


def _execute_blocking(job: str, revision: str, operation: str, ack_scope: str | None) -> dict[str, Any]:
    if not HEX40.fullmatch(revision):
        raise BridgeStop("A complete pinned 40-character commit SHA is required.")
    if not REPO.is_dir() or not VENV_PYTHON.is_file():
        raise BridgeStop("Verified cloud installation unavailable.")
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Prevent two concurrent callers from checking out or executing simultaneously.
    with (STATE_DIR / "operator.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BridgeStop("Another IRONMAN job is running; no concurrent execution.") from exc
        origin = _require_ok(_run("git", "remote", "get-url", "origin"), "Origin")
        if not ORIGIN.fullmatch(origin):
            raise BridgeStop("Untrusted GitHub origin.")
        change = _require_ok(_run("git", "status", "--porcelain", "--untracked-files=normal"), "Worktree")
        if change:
            raise BridgeStop("Local working tree is not clean; preserving local modifications.")
        _require_ok(_run("git", "fetch", "--no-tags", "--depth=1", "origin", BRANCH, timeout=60), "Fetch")
        sha = _require_ok(_run("git", "rev-parse", "FETCH_HEAD"), "Revision")
        if sha != revision:
            raise BridgeStop("Pinned revision differs from current trusted branch tip.")
        # Do not mutate the server until a matching, trusted, explicit revision exists.
        if operation == "execute":
            _require_ok(_run("git", "checkout", "--detach", revision, timeout=35), "Checkout")
        else:
            # Preview may validate only the currently deployed registry.
            return {
                "success": True, "stage": "PREVIEW", "job": job,
                "revision": revision, "provider_writes": 0,
                "message": "Commit verified; execute will check out, test and run the approved job.",
            }
        spec = _check_job(job, operation, ack_scope)
        kind = spec["mode"]
        command = [str(VENV_PYTHON), "-m", "pytest", "-q", spec["test"]]
        _require_ok(_run(*command, timeout=125), "Approved job tests")
        script = REPO / spec["script"]
        # Only a trusted checked-out script path. Never shell=True / caller argv.
        proc = _run(str(VENV_PYTHON), str(script), timeout=175)
        # Strip any accidental bearer/cookie/password strings from returned logs.
        output = re.sub(
            r"(?i)(authorization|bearer|cookie|password|secret|token)\s*[:=]\s*\S+",
            "[redacted]", proc.stdout[-MAX_STDOUT:],
        )
        # Fail CLOSED: unknown write outcomes MUST be read back, not retried.
        stage = "DONE" if proc.returncode == 0 else "STOP_REVIEW"
        return {
            "success": proc.returncode == 0,
            "stage": stage, "job": job, "revision": revision,
            "mode": kind, "scope": spec["scope"], "output": output,
            "exit_code": proc.returncode,
            "never_retry_ambiguous_post": kind == GUARDED_WRITE,
        }


async def tp_ironman_operator(
    job: str, revision: str, operation: str = "preview",
    ack_scope: str | None = None,
) -> dict[str, Any]:
    """Execute a version-pinned, repo-registered job, not caller supplied shell."""
    if operation not in {"preview", "execute"}:
        return {"isError": True, "error_code": "INVALID_OPERATION"}
    if athlete_override.get() is not None:
        return {"isError": True, "error_code": "ATHLETE_TARGET_FORBIDDEN"}
    async with TPClient() as client:
        me = await client._get_user_data()
        if not isinstance(me, dict) or me.get("personId") != OWNER:
            return {"isError": True, "error_code": "ACCOUNT_MISMATCH"}
    try:
        outcome = await asyncio.to_thread(_execute_blocking, job, revision, operation, ack_scope)
        if not outcome.get("success"):
            outcome["isError"] = True
        return outcome
    except BridgeStop as exc:
        return {"isError": True, "error_code": "SAFE_STOP", "message": str(exc)}
