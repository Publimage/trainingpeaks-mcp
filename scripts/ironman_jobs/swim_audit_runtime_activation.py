"""Enable only the independently pinned CSS sample in the existing TP bridge.

Writes one local configuration field, never TrainingPeaks or credentials.
The public pins identify the authorized sample without publishing private IDs.
No general remote administration and no changes to the Radar allowlist.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tp_mcp.swim_audit_bridge import build_swim_input, validate_target

TARGET_PIN = "2ee077897a433dbdda4d0dfeb89a7236aa5d78475fedd5794ee1813dd80bc87a"
LIBRARY_PIN = "29d15baaec77b4fca0a1541f8f96e0b95ebd98842b09fabe5f44b3be23dcbeea"
CONFIG = Path("/home/ironman/.config/ironman/private_bridge.json")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def need(ok, code):
    if not ok:
        raise RuntimeError(code)


def checked_config(path):
    need(path.is_file() and not path.is_symlink() and not path.parent.is_symlink(),
         "CONFIG_PATH_NOT_REGULAR")
    need(path.stat().st_uid == os.getuid(), "CONFIG_OWNER_MISMATCH")
    raw = path.read_bytes()
    need(len(raw) <= 65536, "CONFIG_TOO_LARGE")
    data = json.loads(raw)
    need(type(data) is dict and data.get("host") == "10.114.0.2"
         and data.get("port") == 8787, "CONFIG_BIND_MISMATCH")
    need("10.114.0.3" in data.get("allowed_sources", []), "PREFECT_SOURCE_NOT_CONFIGURED")
    return raw, data


def enable_sample(path, target):
    target = validate_target(target)
    need(digest(target) == TARGET_PIN, "TARGET_NOT_APPROVED")
    before_raw, before = checked_config(path)
    current = before.get("allowed_swim_templates", [])
    need(current in ([], [target]), "OTHER_SWIM_TARGETS_PRESENT")
    if current == [target]:
        return {"changed": False, "config_sha256": hashlib.sha256(before_raw).hexdigest()}
    after = copy.deepcopy(before)
    after["allowed_swim_templates"] = [target]
    backup_dir = path.parent / "swim-audit-backups"
    need(not backup_dir.is_symlink(), "BACKUP_PATH_NOT_REGULAR")
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    backup = backup_dir / (hashlib.sha256(before_raw).hexdigest() + ".json")
    if backup.exists():
        need(not backup.is_symlink() and backup.read_bytes() == before_raw, "BACKUP_CONFLICT")
    else:
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(before_raw)
            stream.flush()
            os.fsync(stream.fileno())
    need(path.read_bytes() == before_raw, "CONFIG_CHANGED_BEFORE_WRITE")
    encoded = (json.dumps(after, sort_keys=True, indent=2) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=".swim-config-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    raw, readback = checked_config(path)
    need(readback == after, "CONFIG_READBACK_MISMATCH")
    baseline = dict(readback)
    baseline.pop("allowed_swim_templates")
    expected_baseline = dict(before)
    expected_baseline.pop("allowed_swim_templates", None)
    need(baseline == expected_baseline, "RADAR_CONFIGURATION_CHANGED")
    return {"changed": True, "config_sha256": hashlib.sha256(raw).hexdigest()}


async def approved_target(client):
    response = await client.get("/exerciselibrary/v2/libraries")
    need(response.is_error is False and type(response.data) is list, "LIBRARY_READ_FAILED")
    matches = []
    for library in response.data:
        if type(library) is not dict:
            continue
        if type(library.get("ownerId")) is not int or type(library.get("exerciseLibraryId")) is not int:
            continue
        identity = {"owner_id": str(library["ownerId"]),
                    "container_id": str(library["exerciseLibraryId"])}
        if digest(identity) == LIBRARY_PIN:
            matches.append(identity)
    need(len(matches) == 1, "PINNED_LIBRARY_NOT_UNIQUE")
    identity = matches[0]
    response = await client.get("/exerciselibrary/v2/libraries/" + identity["container_id"] + "/items")
    need(response.is_error is False and type(response.data) is list, "TEMPLATE_READ_FAILED")
    matches = []
    for item in response.data:
        if type(item) is not dict or type(item.get("exerciseLibraryItemId")) is not int:
            continue
        target = {"provider": "trainingpeaks", "resource_kind": "library_template",
                  **identity, "workout_id": str(item["exerciseLibraryItemId"])}
        if digest(target) == TARGET_PIN:
            matches.append(target)
    need(len(matches) == 1, "PINNED_TEMPLATE_NOT_UNIQUE")
    target = matches[0]
    evidence = await build_swim_input({"target": target}, [target], client=client)
    need(evidence["item"]["distancePlanned"] == 2200, "CSS_DISTANCE_CHANGED")
    return target


def runtime_revision():
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                            check=True, capture_output=True, text=True, timeout=5)
    return result.stdout.strip()


def require_host():
    need(socket.gethostname() == "ironman-tp-mcp", "WRONG_HOST")
    need(os.getuid() != 0, "NONROOT_RUNTIME_REQUIRED")


async def configure():
    require_host()
    from tp_mcp.client import TPClient
    async with TPClient() as client:
        target = await approved_target(client)
    result = enable_sample(CONFIG, target)
    return {"stage": "SWIM_CSS_CONFIG_FILE_VERIFIED", **result,
            "target_sha256": TARGET_PIN, "allowed_template_count": 1,
            "revision": runtime_revision(), "provider_writes": 0,
            "radar_configuration_preserved": True, "reload_required": True,
            "prefect_execution_verified": False}


async def readback():
    require_host()
    _, config = checked_config(CONFIG)
    targets = config.get("allowed_swim_templates")
    need(type(targets) is list and len(targets) == 1 and digest(targets[0]) == TARGET_PIN,
         "CONFIG_SINGLE_SAMPLE_MISMATCH")
    need("10.114.0.2" in config.get("allowed_sources", []), "LOCAL_READBACK_SOURCE_NOT_ALLOWED")
    target = targets[0]
    from tp_mcp.swim_audit_bridge import SwimAuditBridgeClient
    client = SwimAuditBridgeClient(target)
    first = await client.get("/exerciselibrary/v2/libraries/" + target["container_id"] + "/items")
    second = await client.get("/exerciselibrary/v2/libraries/" + target["container_id"] + "/items")
    need(digest(first.data) == digest(second.data), "TEMPLATE_CHANGED_DURING_READBACK")
    return {"stage": "SWIM_CSS_LIVE_BRIDGE_READBACK_PASS", "revision": runtime_revision(),
            "target_sha256": TARGET_PIN, "allowed_template_count": 1,
            "distance_planned_m": first.data[0]["distancePlanned"],
            "template_projection_sha256": digest(first.data[0]),
            "provider_writes": 0, "prefect_execution_verified": False,
            "drive_source_read": False}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(configure()), sort_keys=True))
