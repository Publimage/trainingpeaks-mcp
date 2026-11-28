"""Purely read-only state inspection for the IRONMAN Training Plan publisher.

This endpoint cannot execute GitHub jobs, fetch or check out a branch,
write TrainingPeaks, or modify the operator's local worktree. It exists to
avoid using the mixed read/write operator just to inspect readiness.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OWNER = 2116886
ROOT = Path("/home/ironman/trainingpeaks-mcp")
JOBS_FILE = Path("data/ironman_operator_jobs.json")
MANIFEST_FILE = Path("data/ironman_reviewed_plan_patch.json")
PREVIEW_JOB = "reviewed_plan_patch_preview"
PUBLISH_JOB = "reviewed_plan_patch_publish"


def _read_limited_json(path: Path) -> dict[str, Any] | None:
    """Reject symlinks and oversized data; no code, subprocess or writes."""
    if path.is_symlink() or not path.is_file():
        return None
    try:
        if path.stat().st_size > 300_000:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def inspect_publisher(repo: Path = ROOT) -> dict[str, Any]:
    """Return a bounded, no-side-effect readiness snapshot."""
    registry = _read_limited_json(repo / JOBS_FILE)
    manifest = _read_limited_json(repo / MANIFEST_FILE)
    jobs = registry.get("jobs") if registry else None
    valid_registry = (
        registry is not None
        and registry.get("schema") == "IRONMAN_OPERATOR_JOBS_V1"
        and isinstance(jobs, list)
    )
    registered: dict[str, bool] = {}
    for name, mode in ((PREVIEW_JOB, "READ_ONLY"), (PUBLISH_JOB, "GUARDED_WRITE")):
        registered[name] = bool(
            valid_registry
            and any(isinstance(entry, dict)
                    and entry.get("name") == name
                    and entry.get("mode") == mode
                    and entry.get("owner_id") == OWNER
                    for entry in jobs)
        )
    schema_valid = bool(
        manifest
        and manifest.get("schema") == "IRONMAN_REVIEWED_PLAN_PATCH_CONFIG_V1"
        and type(manifest.get("configured")) is bool
    )
    configured = bool(schema_valid and manifest["configured"] is True)
    result = {
        "stage": "IRONMAN_PUBLISHER_READ_ONLY_STATUS",
        "account_owner_id": OWNER,
        "registry_readable": bool(valid_registry),
        "jobs_registered": registered,
        "manifest_readable": schema_valid,
        "manifest_configured": configured,
        "status": "REVIEWED_BATCH_PENDING" if not configured else "REVIEWED_BATCH_PRESENT_UNVERIFIED",
        "preview_health_check_is_not_write_proof": True,
        "live_writer_verified": False,
        "provider_writes": 0,
        "tool_side_effects": "none",
    }
    return result


async def tp_get_ironman_publisher_status() -> dict[str, Any]:
    """Coach-authenticated read, independent from the mutating operator."""
    from tp_mcp.client import TPClient
    from tp_mcp.client.context import athlete_override

    if athlete_override.get() is not None:
        return {"isError": True, "error_code": "ATHLETE_TARGET_FORBIDDEN"}
    async with TPClient() as client:
        me = await client._get_user_data()
        if not isinstance(me, dict) or me.get("personId") != OWNER:
            return {"isError": True, "error_code": "ACCOUNT_MISMATCH"}
    return inspect_publisher()
