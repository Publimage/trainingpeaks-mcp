"""Run the independently reviewed CSS 2200 m audit, read-only, as non-root.

The private manifest binds one target/source, pin and exact repository revision.
No credentials, private identities, source data or workout data live in GitHub.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[2]
REPORT_DIR = Path("/var/lib/ironman-prefect/swim-audit")
MANIFEST = REPORT_DIR / "css_canary_request.json"
GOOGLE_KEY = Path("/var/lib/ironman-prefect/credentials/radar-drive-reader.json")
PINNED_TARGET_SHA256 = "2ee077897a433dbdda4d0dfeb89a7236aa5d78475fedd5794ee1813dd80bc87a"
PINNED_RECORD_SHA256 = "e935d340c9abecbcebc5c90ba966c02b8034ebab20be11c821b98b72682c664d"
EXPECTED_ORIGIN = "https://github.com/Publimage/trainingpeaks-mcp.git"


class CanaryStop(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise CanaryStop(code)


def sha_json(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()


def private_regular_file(path: Path, uid: int) -> bytes:
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and not path.is_symlink(), "PRIVATE_FILE_NOT_REGULAR")
    require(metadata.st_uid == uid and not metadata.st_mode & 0o077, "PRIVATE_FILE_PERMISSIONS")
    require(metadata.st_size <= 65536, "PRIVATE_FILE_TOO_LARGE")
    return path.read_bytes()


def validate_manifest(data: dict, revision: str) -> dict:
    require(type(data) is dict and set(data) == {"schema", "revision", "request"}, "MANIFEST_FIELDS")
    require(data["schema"] == "IRONMAN_CSS_PREFECT_CANARY_V1", "MANIFEST_SCHEMA")
    require(type(revision) is str and re.fullmatch("[0-9a-f]{40}", revision) is not None,
            "RUNTIME_REVISION_INVALID")
    require(data["revision"] == revision, "RUNTIME_REVISION_MISMATCH")
    req = data["request"]
    require(type(req) is dict and set(req) == {
        "target", "document_id", "document_title", "section",
        "reviewed_record_sha256", "validator_revision"
    }, "REQUEST_FIELDS")
    require(sha_json(req["target"]) == PINNED_TARGET_SHA256, "TARGET_NOT_REVIEWED")
    require(req["reviewed_record_sha256"] == PINNED_RECORD_SHA256, "RECORD_NOT_REVIEWED")
    require(req["validator_revision"] == revision, "VALIDATOR_REVISION_MISMATCH")
    require(req["document_title"] == "11_AGENT_ORCHESTRATION_ROADMAP" and
            req["section"] == "css2200_pause300_after1200_v1", "SOURCE_SELECTOR_MISMATCH")
    return req


def validate_child_output(value: object) -> dict:
    if (type(value) is not dict or value.get("stage") != "SWIM_CSS_PREFECT_REPORT_RECORDED"
            or value.get("trainingpeaks_writes") != 0
            or value.get("source_rechecked") is not True
            or value.get("template_rechecked") is not True
            or value.get("audit_status") not in {"PASS", "PARTIAL", "FAIL", "UNVERIFIABLE"}):
        raise RuntimeError("SWIM_CSS_CHILD_REPORT_INVALID")
    return value


def runtime_revision() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                              text=True, check=True, timeout=8).stdout.strip()
    require(git("remote", "get-url", "origin") == EXPECTED_ORIGIN, "GIT_ORIGIN_MISMATCH")
    return git("rev-parse", "HEAD")


def store_report(report: dict) -> tuple[str, str]:
    raw = json.dumps(report, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    require(len(raw) <= 2 * 1024 * 1024, "REPORT_TOO_LARGE")
    name = "css2200_prefect_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json"
    path = REPORT_DIR / name
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as dest:
        dest.write(raw)
        dest.flush()
        os.fsync(dest.fileno())
    require(path.read_bytes() == raw, "REPORT_READBACK_MISMATCH")
    return str(path), hashlib.sha256(raw).hexdigest()


def run_once() -> dict:
    user = pwd.getpwnam("ironmanprefect")
    require(os.getuid() == user.pw_uid and os.getuid() != 0, "NONROOT_PREFECT_USER_REQUIRED")
    directory = REPORT_DIR.lstat()
    require(stat.S_ISDIR(directory.st_mode) and directory.st_uid == os.getuid() and
            not directory.st_mode & 0o077, "REPORT_DIR_PERMISSIONS")
    conf = json.loads(private_regular_file(MANIFEST, os.getuid()))
    private_regular_file(GOOGLE_KEY, os.getuid())
    revision = runtime_revision()
    request = validate_manifest(conf, revision)

    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2.service_account import Credentials
    from scripts.ironman_jobs.swim_audit_acquisition import acquire_swim_audit
    from scripts.ironman_jobs.swim_audit_drive_reader import GoogleDriveSwimSourceReader
    from tp_mcp.swim_audit_bridge import SwimAuditBridgeClient

    google = Credentials.from_service_account_file(
        str(GOOGLE_KEY), scopes=["https://www.googleapis.com/auth/drive.readonly"])
    reader = GoogleDriveSwimSourceReader(AuthorizedSession(google))
    bridge = SwimAuditBridgeClient(request["target"])
    audit = asyncio.run(acquire_swim_audit(request, drive_reader=reader, tp_client=bridge))
    require(audit.get("code") == "SWIM_ACQUISITION_COMPLETE",
            "ACQUISITION_STOP_" + str(audit.get("code", "UNKNOWN")))
    require(audit.get("provider_writes") == 0 and
            audit["acquisition"].get("source_rechecked") is True and
            audit["acquisition"].get("template_rechecked") is True, "ACQUISITION_GUARD")
    require(audit.get("status") in ("PASS", "PARTIAL", "FAIL", "UNVERIFIABLE"),
            "UNKNOWN_AUDIT_STATUS")
    path, digest = store_report(audit)
    return {
        "stage": "SWIM_CSS_PREFECT_REPORT_RECORDED",
        "audit_status": audit["status"],
        "distance_status": audit["report"]["checks"]["distance"]["status"],
        "recovery_status": audit["report"]["checks"]["recoveries"]["status"],
        "report_path": path,
        "report_sha256": digest,
        "source_rechecked": True,
        "template_rechecked": True,
        "revision": revision,
        "trainingpeaks_writes": 0,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(run_once(), sort_keys=True))
    except (CanaryStop, ValueError, TypeError, KeyError, OSError,
            subprocess.SubprocessError) as exc:
        # Never print potentially sensitive provider/source or credential data.
        code = str(exc) if isinstance(exc, CanaryStop) else type(exc).__name__
        print(json.dumps({"stage": "SWIM_CSS_PREFECT_STOP", "code": code}, sort_keys=True))
        raise SystemExit(2)
