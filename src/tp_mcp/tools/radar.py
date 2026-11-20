"""Read the latest persisted Coaching Radar report.

Reports are produced by the Prefect staging flow and written to the TP host
through the private VPC result sink. This tool only reads local JSON state.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RADAR_RESULT_DIR = Path("/home/ironman/.local/state/ironman-radar")


async def tp_get_coaching_radar(athlete_id: str) -> dict[str, Any]:
    value = str(athlete_id).strip()
    if not value.isdigit():
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": "athlete_id must be numeric.",
        }
    path = RADAR_RESULT_DIR / f"latest_{value}.json"
    if not path.exists():
        return {
            "isError": True,
            "error_code": "NOT_FOUND",
            "message": f"No Coaching Radar report stored for athlete {value}.",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "isError": True,
            "error_code": "RADAR_STATE_ERROR",
            "message": "Stored Coaching Radar report is unreadable.",
        }
    if str(payload.get("athlete_id")) != value:
        return {
            "isError": True,
            "error_code": "RADAR_STATE_ERROR",
            "message": "Stored Coaching Radar athlete identity mismatch.",
        }
    return payload
