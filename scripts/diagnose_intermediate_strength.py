"""Read-only diagnosis for the private Intermediate Strength Builder gate.

This helper prints bounded provider identity metadata only. It never writes,
lists athletes, or displays tokens, headers, cookies or raw provider objects.
"""
from __future__ import annotations

import asyncio
import json
import sys

import httpx

from tp_mcp.client import TPClient
from tp_mcp.tools.strength import STRENGTH_API_BASE, _access, _headers

PLAN_IDS = (684543, 684602)
WORKOUT_IDS = (33903234, 33966177, 33969338)
IDENTITY_KEYS = (
    "id", "planId", "calendarId", "trainingPlanId", "planWorkoutId",
    "sourcePlanId", "parentPlanId", "athleteId", "userId",
    "calendarType", "isPlanWorkout", "workoutType", "prescribedDate",
    "title", "workoutCount", "weekCount", "startDate",
)


def _safe_identity(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        return {"error": "unexpected_response_shape"}
    result: dict[str, object] = {
        key: data[key]
        for key in IDENTITY_KEYS
        if key in data and isinstance(data[key], (str, int, float, bool, type(None)))
        and len(str(data[key])) <= 200
    }
    result["extra_identity_key_names"] = sorted(
        key for key in data
        if isinstance(key, str)
        and any(term in key.lower() for term in ("calendar", "plan", "source", "parent"))
        and key not in IDENTITY_KEYS
    )[:20]
    return result


async def main() -> int:
    output: dict[str, object] = {"read_only": True, "plans": {}, "strength": {}}
    async with TPClient() as client:
        for plan_id in PLAN_IDS:
            result = await client.get(f"/plans/v1/plans/{plan_id}")
            if result.is_error:
                output["plans"][str(plan_id)] = {"error": "plan_read_failed"}
            else:
                output["plans"][str(plan_id)] = _safe_identity(result.data)

        _, access, error = await _access(client)
        if error or not access:
            output["strength"]["error"] = "authentication_unavailable"
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 1

        async with httpx.AsyncClient(timeout=20.0) as http:
            for workout_id in WORKOUT_IDS:
                try:
                    response = await http.get(
                        f"{STRENGTH_API_BASE}/rx/activity/v1/workouts/{workout_id}",
                        headers=_headers(access),
                    )
                    if response.status_code != 200:
                        output["strength"][str(workout_id)] = {
                            "http_status": response.status_code
                        }
                        continue
                    body = response.json()
                    output["strength"][str(workout_id)] = _safe_identity(
                        body.get("data") if isinstance(body, dict) else None
                    )
                except (httpx.RequestError, ValueError, TypeError):
                    output["strength"][str(workout_id)] = {"error": "read_failed"}

    # The workout detail JSON does not contain an authoritative plan id:
    # the same calendarId occurs on both lab and Intermediate items.
    # Query only narrow, read-only candidate PLAN listing routes to establish
    # whether the plan library actually indexes the created Strength workout.
    probes: dict[str, object] = {}
    windows = {
        684543: ("2027-08-02", "2027-08-09"),
        684602: ("2026-10-05", "2026-10-12"),
    }
    async with httpx.AsyncClient(timeout=15.0) as http:
        for plan_id, (start, end) in windows.items():
            base = f"{STRENGTH_API_BASE}/rx/activity/v1/plans/{plan_id}"
            paths = {
                "plan_detail": base,
                "strength_workouts": base + "/workouts",
                "strength_workouts_dates": base + f"/workouts/{start}/{end}",
                "strength_workouts_query": base + f"/workouts?startDate={start}&endDate={end}",
            }
            plan_probes: dict[str, object] = {}
            for label, url in paths.items():
                try:
                    response = await http.get(url, headers=_headers(access))
                    info: dict[str, object] = {"http_status": response.status_code}
                    if response.status_code == 200:
                        if len(response.content) > 500000:
                            info["data"] = "response_too_large_to_summarize"
                        else:
                            try:
                                parsed = response.json()
                            except ValueError:
                                parsed = None
                            if isinstance(parsed, dict):
                                info["top_level_keys"] = list(parsed)[:12]
                                data = parsed.get("data")
                                if isinstance(data, list):
                                    info["items_count"] = len(data)
                                    info["match_ids"] = [
                                        str(it.get("id") or it.get("workoutId"))
                                        for it in data if isinstance(it, dict)
                                        and str(it.get("id") or it.get("workoutId"))
                                        in {"33903234", "33966177", "33969338"}
                                    ]
                                elif isinstance(data, dict):
                                    info["data_keys"] = list(data)[:20]
                                # Search only three already-known workout IDs.
                                # Return booleans, never unfiltered provider JSON.
                                encoded = json.dumps(parsed, ensure_ascii=False)
                                info["known_id_present"] = {
                                    x: x in encoded
                                    for x in ("33903234", "33966177", "33969338")
                                }
                            elif isinstance(parsed, list):
                                info["items_count"] = len(parsed)
                                encoded = json.dumps(parsed, ensure_ascii=False)
                                info["known_id_present"] = {
                                    x: x in encoded
                                    for x in ("33903234", "33966177", "33969338")
                                }
                    plan_probes[label] = info
                except (httpx.RequestError, TypeError, ValueError):
                    plan_probes[label] = {"error": "read_failed"}
            probes[str(plan_id)] = plan_probes
    output["plan_membership_probes"] = probes
    summary = probes if "--membership-only" in sys.argv[1:] else output
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
