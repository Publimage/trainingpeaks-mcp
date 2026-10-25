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
REVIEWED_PLAN_JOBS = frozenset({"reviewed_plan_patch_preview", "reviewed_plan_patch_publish"})


class BridgeStop(Exception):
    """Fail closed with a machine-readable operational failure category."""

    def __init__(self, message: str, *, code: str = "SAFE_STOP") -> None:
        super().__init__(message)
        self.code = code


def _run(*argv: str, timeout: int = 30, request_plan_id: int | None = None,
         request_scope: str | None = None,
         request_workout_ids: list[int] | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        key: value for key, value in os.environ.items()
        if key in {"HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "XDG_CONFIG_HOME"}
    }
    env["HOME"] = str(REPO.parent)
    env["PYTHONPATH"] = str(REPO / "src")
    if request_plan_id is not None:
        env["IRONMAN_REQUEST_TARGET_PLAN_ID"] = str(request_plan_id)
    if request_scope is not None:
        env["IRONMAN_REQUEST_TARGET_SCOPE"] = request_scope
    if request_workout_ids is not None:
        env["IRONMAN_REQUEST_WORKOUT_IDS_JSON"] = json.dumps(
            sorted(request_workout_ids), separators=(",", ":"))
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
    # Fixed optional feature registry; same trusted checkout and _check_job gates.
    # No caller-controlled paths, branch changes, or execution permissions.
    extension_path = REPO / "data/ironman_swim_operator_jobs.json"
    if extension_path.exists():
        try:
            extra = json.loads(extension_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BridgeStop("Swim job registry missing or invalid.") from exc
        if (extra.get("schema") != "IRONMAN_OPERATOR_JOBS_V1"
            or extra.get("owner") != OWNER
            or not isinstance(extra.get("jobs"), list)):
            raise BridgeStop("Unapproved swim job registry.")
        entries = entries + extra["jobs"]
    result = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise BridgeStop("Invalid registry entry.")
        if entry["name"] in result:
            raise BridgeStop("Duplicate job registration.")
        result[entry["name"]] = entry
    return result


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


def _check_reviewed_manifest_target(job: str, target_plan_id: int | None) -> None:
    """Independent request-to-manifest gate. Never infer the target from JSON."""
    if job not in REVIEWED_PLAN_JOBS:
        return
    if type(target_plan_id) is not int or target_plan_id <= 0:
        raise BridgeStop("TARGET_PLAN_ID_REQUIRED_FOR_REVIEWED_PUBLISHER")
    path = REPO / "data/ironman_reviewed_plan_patch.json"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BridgeStop("REVIEWED_MANIFEST_UNREADABLE") from exc
    if cfg.get("configured") is False:
        if job == "reviewed_plan_patch_publish":
            raise BridgeStop("REVIEWED_MANIFEST_NOT_ACTIVE")
        return
    if cfg.get("configured") is not True:
        raise BridgeStop("REVIEWED_MANIFEST_INVALID")
    actual = (cfg.get("manifest") or {}).get("plan_id")
    if actual != target_plan_id:
        raise BridgeStop("STOP_TARGET_MISMATCH")



def _check_reviewed_manifest_request(job: str, requested_scope: str | None,
                                     requested_workout_ids: list[int] | None) -> None:
    """Require the current operation scope AND exact workout IDs independently.

    A completed batch from the SAME Training Plan must never be reinterpreted
    as a new request merely because target_plan_id still matches.
    """
    if job not in REVIEWED_PLAN_JOBS:
        return
    try:
        cfg = json.loads((REPO / "data/ironman_reviewed_plan_patch.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BridgeStop("REVIEWED_MANIFEST_UNREADABLE") from exc
    if cfg.get("configured") is False:
        # Preserve the existing inactive, provider-free preview health check.
        # The separate target gate still blocks inactive publish.
        return
    if cfg.get("configured") is not True:
        raise BridgeStop("REVIEWED_MANIFEST_INVALID")
    if not isinstance(requested_scope, str) or not requested_scope.startswith("trainingpeaks:plan:"):
        raise BridgeStop("REQUEST_SCOPE_REQUIRED_FOR_REVIEWED_PUBLISHER")
    ids = requested_workout_ids
    if (type(ids) is not list or not 1 <= len(ids) <= 150
            or any(type(x) is not int or x <= 0 for x in ids)
            or len(set(ids)) != len(ids)):
        raise BridgeStop("REQUEST_WORKOUT_IDS_REQUIRED_FOR_REVIEWED_PUBLISHER")
    manifest = cfg.get("manifest")
    if not isinstance(manifest, dict):
        raise BridgeStop("REVIEWED_MANIFEST_INVALID")
    if manifest.get("scope") != requested_scope:
        raise BridgeStop("STOP_REQUEST_SCOPE_MISMATCH")
    items = manifest.get("items")
    if not isinstance(items, list):
        raise BridgeStop("REVIEWED_MANIFEST_ITEMS_INVALID")
    actual_ids = [x.get("workout_id") for x in items if isinstance(x, dict)]
    if len(actual_ids) != len(items) or any(type(x) is not int or x <= 0 for x in actual_ids):
        raise BridgeStop("REVIEWED_MANIFEST_ITEMS_INVALID")
    if sorted(ids) != sorted(actual_ids):
        raise BridgeStop("STOP_REQUEST_RESOURCE_MISMATCH")


def _execute_blocking(job: str, revision: str, operation: str, ack_scope: str | None,
                      target_plan_id: int | None = None,
                      request_scope: str | None = None,
                      requested_workout_ids: list[int] | None = None) -> dict[str, Any]:
    if not HEX40.fullmatch(revision):
        raise BridgeStop("A complete pinned 40-character commit SHA is required.")
    # Job registration is generic. Bind each reviewed plan execution to the
    # caller-confirmed plan ID independently of any persisted JSON manifest.
    if operation == "execute" and job in REVIEWED_PLAN_JOBS:
        if type(target_plan_id) is not int or target_plan_id <= 0:
            raise BridgeStop("TARGET_PLAN_ID_REQUIRED_FOR_REVIEWED_PUBLISHER")
    if not REPO.is_dir() or not VENV_PYTHON.is_file():
        raise BridgeStop("Verified cloud installation unavailable.")
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Prevent two concurrent callers from checking out or executing simultaneously.
    with (STATE_DIR / "operator.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BridgeStop("Another IRONMAN job is running; no concurrent execution.", code="OPERATOR_BUSY") from exc
        origin = _require_ok(_run("git", "remote", "get-url", "origin"), "Origin")
        if not ORIGIN.fullmatch(origin):
            raise BridgeStop("Untrusted GitHub origin.")
        change = _require_ok(_run("git", "status", "--porcelain", "--untracked-files=normal"), "Worktree")
        if change:
            raise BridgeStop("Local working tree is not clean; preserving local modifications.", code="WORKTREE_DIRTY")
        _require_ok(_run("git", "fetch", "--no-tags", "--depth=1", "origin", BRANCH, timeout=60), "Fetch")
        sha = _require_ok(_run("git", "rev-parse", "FETCH_HEAD"), "Revision")
        if sha != revision:
            raise BridgeStop(
                f"Pinned revision differs from current trusted branch tip "
                f"(requested={revision[:12]}, current={sha[:12]}). No checkout performed.",
                code="REVISION_DRIFT",
            )
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
        # Check against the request before creating a write receipt or invoking a job.
        _check_reviewed_manifest_target(job, target_plan_id)
        _check_reviewed_manifest_request(job, request_scope, requested_workout_ids)
        kind = spec["mode"]
        command = [str(VENV_PYTHON), "-m", "pytest", "-q", spec["test"]]
        _require_ok(_run(*command, timeout=125), "Approved job tests")
        script = REPO / spec["script"]
        # Guarded writes are non-idempotent. Claim a durable local receipt before
        # executing. Any crash/timeout leaves a STOP requiring provider readback.
        receipt_path = None
        if kind == GUARDED_WRITE:
            fingerprint = hashlib.sha256(
                f"{job}|{revision}|{spec['scope']}".encode("utf-8")
            ).hexdigest()[:32]
            receipt_path = STATE_DIR / f"{fingerprint}.json"
            if receipt_path.exists():
                raise BridgeStop(
                    "Protected job already attempted; inspect provider state before any repeat.",
                    code="WRITE_RECEIPT_EXISTS",
                )
            pending = {
                "job": job, "revision": revision, "scope": spec["scope"],
                "state": "STARTED_UNVERIFIED",
            }
            tmp = receipt_path.with_suffix(".tmp")
            with tmp.open("x", encoding="utf-8") as out:
                os.chmod(tmp, 0o600)
                json.dump(pending, out)
                out.flush()
                os.fsync(out.fileno())
            tmp.replace(receipt_path)

        # Only a trusted checked-out script path. Never shell=True / caller argv.
        if job in REVIEWED_PLAN_JOBS:
            proc = _run(str(VENV_PYTHON), str(script), timeout=175,
                        request_plan_id=target_plan_id, request_scope=request_scope,
                        request_workout_ids=requested_workout_ids)
        else:
            proc = _run(str(VENV_PYTHON), str(script), timeout=175)
        if receipt_path is not None:
            audit = {
                "job": job, "revision": revision, "scope": spec["scope"],
                "state": "DONE_NEEDS_PROVIDER_AUDIT" if proc.returncode == 0 else "STOP_REVIEW",
                "exit_code": proc.returncode,
            }
            tmp = receipt_path.with_suffix(".tmp")
            with tmp.open("x", encoding="utf-8") as out:
                os.chmod(tmp, 0o600)
                json.dump(audit, out)
                out.flush()
                os.fsync(out.fileno())
            tmp.replace(receipt_path)
        # Strip any accidental bearer/cookie/password strings from returned logs.
        from tp_mcp.private_bridge import _redact_admin_text
        output = _redact_admin_text(proc.stdout[-MAX_STDOUT:])
        # Fail CLOSED: unknown write outcomes MUST be read back, not retried.
        stage = "DONE" if proc.returncode == 0 else "STOP_REVIEW"
        return {
            "success": proc.returncode == 0,
            "stage": stage, "job": job, "revision": revision,
            "mode": kind, "scope": spec["scope"], "output": output,
            "exit_code": proc.returncode,
            "never_retry_ambiguous_post": kind == GUARDED_WRITE,
            "error_code": "JOB_SCRIPT_FAILED" if proc.returncode != 0 else None,
        }


async def tp_ironman_operator(
    job: str, revision: str, operation: str = "preview",
    ack_scope: str | None = None,
    target_plan_id: int | None = None,
    request_scope: str | None = None,
    requested_workout_ids: list[int] | None = None,
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
        outcome = await asyncio.to_thread(_execute_blocking, job, revision, operation,
                                          ack_scope, target_plan_id,
                                          request_scope, requested_workout_ids)
        if not outcome.get("success"):
            outcome["isError"] = True
        return outcome
    except BridgeStop as exc:
        return {"isError": True, "error_code": exc.code, "message": str(exc)}
