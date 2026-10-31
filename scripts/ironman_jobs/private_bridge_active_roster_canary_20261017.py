"""Read-only canary: verify running private bridge accepts the full active Radar roster."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

URL = "http://10.114.0.2:8787/v1/radar-input"
ATHLETES = [
    "6133559", "3657374", "5590716", "5976093", "4732548",
    "6605664", "2932097", "6583514", "6610602", "4480273",
]


def probe(athlete_id: str) -> dict:
    payload = json.dumps({
        "athlete_id": athlete_id,
        "start_date": "2026-10-17",
        "end_date": "2026-10-17",
    }).encode("utf-8")
    req = urllib.request.Request(
        URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {
                "athlete_id": athlete_id,
                "http_status": response.status,
                "schema": body.get("schema"),
                "workout_count": len(body.get("workouts") or []),
                "trainingpeaks_writes": body.get("trainingpeaks_writes", 0),
            }
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode("utf-8"))
        return {
            "athlete_id": athlete_id,
            "http_status": exc.code,
            "error": body.get("error"),
            "trainingpeaks_writes": 0,
        }


def main() -> int:
    results = [probe(x) for x in ATHLETES]
    failures = [
        x for x in results
        if x.get("http_status") != 200 or x.get("schema") != "IRONMAN_TP_RADAR_INPUT_V1"
    ]
    print("PRIVATE_BRIDGE_ACTIVE_ROSTER_CANARY")
    print(json.dumps({
        "expected": len(ATHLETES),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "results": results,
        "trainingpeaks_writes": 0,
    }))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
