"""Read-only live probe of the running private bridge allowlist."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

URL = "http://10.114.0.2:8787/v1/radar-input"
ATHLETE_ID = "4480273"


def main() -> int:
    payload = json.dumps({
        "athlete_id": ATHLETE_ID,
        "start_date": "2026-10-16",
        "end_date": "2026-10-17",
    }).encode("utf-8")
    req = urllib.request.Request(
        URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = json.loads(exc.read().decode("utf-8"))
    print("PRIVATE_BRIDGE_LIVE_ALLOWLIST_PROBE")
    print(json.dumps({
        "athlete_id": ATHLETE_ID,
        "http_status": status,
        "schema": body.get("schema"),
        "error": body.get("error"),
        "trainingpeaks_writes": body.get("trainingpeaks_writes", 0),
    }))
    return 0 if status == 200 and body.get("schema") == "IRONMAN_TP_RADAR_INPUT_V1" else 2


if __name__ == "__main__":
    raise SystemExit(main())
