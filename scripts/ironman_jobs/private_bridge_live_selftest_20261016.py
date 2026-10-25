"""Read-only live proof for the private TrainingPeaks radar bridge."""
from __future__ import annotations

import json
import urllib.request

BASE = "http://10.114.0.2:8787"


def _json_request(req: urllib.request.Request, timeout: int = 90):
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def main() -> int:
    status, health = _json_request(urllib.request.Request(BASE + "/health"))
    if status != 200 or health.get("mode") != "READ_ONLY":
        raise RuntimeError("BRIDGE_HEALTH_FAILED")

    payload = json.dumps({
        "athlete_id": "2932097",
        "start_date": "2026-10-14",
        "end_date": "2026-10-18",
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/v1/radar-input",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    status, data = _json_request(req)
    if status != 200:
        raise RuntimeError("BRIDGE_RADAR_HTTP_FAILED")
    if data.get("schema") != "IRONMAN_TP_RADAR_INPUT_V1":
        raise RuntimeError("BRIDGE_SCHEMA_MISMATCH")
    if data.get("athlete_id") != 2932097:
        raise RuntimeError("BRIDGE_ATHLETE_MISMATCH")
    if data.get("trainingpeaks_writes") != 0:
        raise RuntimeError("BRIDGE_WRITE_GUARD_FAILED")
    if not data.get("workouts"):
        raise RuntimeError("BRIDGE_NO_WORKOUTS")
    print("PRIVATE_BRIDGE_LIVE_PASS")
    print(json.dumps({
        "workouts": len(data["workouts"]),
        "completed_details": len(data.get("completed_details", [])),
        "metrics_count": (data.get("metrics") or {}).get("count", 0),
        "trainingpeaks_writes": 0,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
