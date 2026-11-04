"""Read-only preflight for Coaching Radar Google Drive context runtime.

Checks local runtime/configuration only. No Google API call, no Drive write,
no TrainingPeaks write, no service restart.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.ironman_jobs.coaching_radar_context_sources_v0 import load_private_source_config

ROSTER = Path("/opt/ironman-prefect/radar-src/data/coaching_radar_alberto_group_v1.json")
DEFAULT_CREDENTIALS = Path("/var/lib/ironman-prefect/credentials/radar-drive-reader.json")
DEFAULT_SOURCES = Path("/var/lib/ironman-prefect/credentials/radar-context-sources.json")


def _secure_file(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "MISSING"
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        return False, f"PERMISSIONS_TOO_OPEN:{oct(mode)}"
    return True, oct(mode)


def _roster_ids(path: Path) -> set[int]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        int(item["athlete_id"])
        for item in raw["athletes"]
        if item.get("enabled")
    }


def preflight(credentials_file: Path, sources_file: Path, roster_file: Path) -> dict:
    result = {
        "schema": "IRONMAN_RADAR_DRIVE_RUNTIME_PREFLIGHT_V1",
        "credentials_file": str(credentials_file),
        "sources_file": str(sources_file),
        "credentials": "UNKNOWN",
        "sources": "UNKNOWN",
        "google_auth_dependency": "UNKNOWN",
        "source_roster_count": 0,
        "drive_writes": 0,
        "trainingpeaks_writes": 0,
        "ai_calls": 0,
    }

    credentials_ok, credentials_detail = _secure_file(credentials_file)
    if credentials_ok:
        raw = json.loads(credentials_file.read_text(encoding="utf-8"))
        if raw.get("type") != "service_account" or not raw.get("client_email") or not raw.get("private_key"):
            result["credentials"] = "INVALID_SERVICE_ACCOUNT_JSON"
        else:
            result["credentials"] = "READY"
            result["credential_identity_present"] = True
    else:
        result["credentials"] = credentials_detail

    sources_ok, sources_detail = _secure_file(sources_file)
    if sources_ok:
        try:
            active_ids = _roster_ids(roster_file)
            loaded = load_private_source_config(sources_file, active_athlete_ids=active_ids)
            result["sources"] = "READY"
            result["source_roster_count"] = len(loaded["athlete_cards"])
            result["specialist_document_count"] = len(loaded["specialist_documents"])
        except Exception as exc:
            result["sources"] = f"INVALID:{type(exc).__name__}:{exc}"
    else:
        result["sources"] = sources_detail

    try:
        import google.auth  # noqa: F401
        result["google_auth_dependency"] = "READY"
    except ImportError:
        result["google_auth_dependency"] = "MISSING"

    result["ready_for_live_canary"] = (
        result["credentials"] == "READY"
        and result["sources"] == "READY"
        and result["google_auth_dependency"] == "READY"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials-file", default=str(DEFAULT_CREDENTIALS))
    parser.add_argument("--sources-file", default=str(DEFAULT_SOURCES))
    parser.add_argument("--roster-file", default=str(ROSTER))
    args = parser.parse_args()

    outcome = preflight(
        Path(args.credentials_file),
        Path(args.sources_file),
        Path(args.roster_file),
    )
    print("RADAR_DRIVE_RUNTIME_PREFLIGHT")
    print(json.dumps(outcome, sort_keys=True))
    return 0 if outcome["ready_for_live_canary"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
