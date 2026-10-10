"""Read-only cross-window Strength membership audit for two private TEST plans.

Training Plan dates below are *technical storage coordinates* used to read native
provider records; workouts belong to relative (week, weekday) slots.
No POST/PATCH/DELETE, no athlete calendars, no raw payloads or credentials.
"""
from __future__ import annotations

import asyncio
import json
import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools.strength import STRENGTH_API_BASE, _access, _headers

LAB = 684543
INTERMEDIATE = 684602
WINDOWS = {
    "lab_technical_window": ("2027-08-02", "2027-08-10"),
    "intermediate_w1_technical_window": ("2026-10-05", "2026-10-13"),
}
KNOWN_IDS = {"33903234", "33966177", "33969338", "33971120"}


def summarize(items: object) -> dict:
    if not isinstance(items, list):
        return {"shape": type(items).__name__}
    matches = []
    for item in items:
        if not isinstance(item, dict):
            continue
        wid = str(item.get("id") or item.get("workoutId") or item.get("activityWorkoutId"))
        if wid in KNOWN_IDS:
            matches.append({"workout_id": wid,
                            "prescribedDate": item.get("prescribedDate") or item.get("workoutDay")})
    return {"item_count": len(items), "known_workouts": matches}


async def main() -> None:
    output = {"read_only": True, "membership": {}}
    async with TPClient() as client:
        for pid in (LAB, INTERMEDIATE):
            p = await client.get(f"/plans/v1/plans/{pid}")
            output[str(pid)] = {
                "workout_count": (p.data or {}).get("workoutCount")
                if not p.is_error and isinstance(p.data, dict) else None
            }
        _, token, err = await _access(client)
        if err or not token:
            print(json.dumps({"error": "auth_not_available", "read_only": True}))
            return
        async with httpx.AsyncClient(timeout=20.0) as h:
            for pid in (LAB, INTERMEDIATE):
                checks = {}
                for label, (start, end) in WINDOWS.items():
                    url = (
                        f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{pid}"
                        f"/workouts/{start}/{end}"
                    )
                    try:
                        resp = await h.get(url, headers=_headers(token))
                        if resp.status_code != 200:
                            checks[label] = {"http_status": resp.status_code}
                            continue
                        raw = resp.json()
                        if isinstance(raw, dict):
                            raw = raw.get("data")
                        checks[label] = summarize(raw)
                    except (httpx.RequestError, ValueError, TypeError):
                        checks[label] = {"error": "native_read_failed"}
                output["membership"][str(pid)] = checks
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
