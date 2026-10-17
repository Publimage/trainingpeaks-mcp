"""Verify the active daily V2 pilot deployment without touching the inactive group schedule."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from uuid import UUID

from prefect.client.orchestration import get_client

DEPLOYMENT = "ironman-coaching-radar-v2/polverari-readonly-daily-v2"
GROUP_DEPLOYMENT = "ironman-coaching-radar-v2/alberto-group-readonly-daily"
OUTPUT = Path("/var/lib/ironman-prefect/radar-pilot-v2")


def _schedule_snapshot(deployment) -> list[dict]:
    raw = deployment.model_dump(mode="json")
    return raw.get("schedules") or []


async def verify_deployment_schedules() -> dict:
    async with get_client() as client:
        pilot = await client.read_deployment_by_name(DEPLOYMENT)
        group = await client.read_deployment_by_name(GROUP_DEPLOYMENT)
    pilot_schedules = _schedule_snapshot(pilot)
    group_schedules = _schedule_snapshot(group)
    if len(pilot_schedules) != 1 or len(group_schedules) != 1:
        raise RuntimeError("RADAR_V2_SCHEDULE_COUNT_MISMATCH")
    ps = pilot_schedules[0]
    gs = group_schedules[0]
    if ps.get("active") is not True:
        raise RuntimeError("RADAR_V2_PILOT_SCHEDULE_NOT_ACTIVE")
    if gs.get("active") is not False:
        raise RuntimeError("RADAR_V2_GROUP_SCHEDULE_NOT_INACTIVE")
    pilot_schedule = ps.get("schedule") or {}
    group_schedule = gs.get("schedule") or {}
    for schedule in (pilot_schedule, group_schedule):
        if schedule.get("cron") != "30 5 * * *":
            raise RuntimeError("RADAR_V2_CRON_MISMATCH")
        if schedule.get("timezone") != "Europe/Rome":
            raise RuntimeError("RADAR_V2_TIMEZONE_MISMATCH")
    return {
        "pilot_schedule_active": True,
        "group_schedule_active": False,
        "cron": "30 5 * * *",
        "timezone": "Europe/Rome",
    }


async def create_run(as_of: str) -> str:
    async with get_client() as client:
        deployment = await client.read_deployment_by_name(DEPLOYMENT)
        run = await client.create_flow_run_from_deployment(
            deployment.id,
            parameters={"as_of": as_of},
        )
        return str(run.id)


async def read_state(run_id: str) -> str:
    async with get_client() as client:
        run = await client.read_flow_run(UUID(run_id))
        return run.state.type.value


def wait(run_id: str, timeout: int = 300) -> str:
    end = time.monotonic() + timeout
    last = "UNKNOWN"
    while time.monotonic() < end:
        last = asyncio.run(read_state(run_id))
        if last == "COMPLETED":
            return last
        if last in {"FAILED", "CRASHED", "CANCELLED"}:
            raise RuntimeError(f"RADAR_V2_PILOT_FAILED:{last}")
        time.sleep(2)
    raise RuntimeError(f"RADAR_V2_PILOT_TIMEOUT:{last}")


def verify_files(as_of: str) -> dict:
    summary = json.loads((OUTPUT / "group_74397" / f"summary_{as_of}.json").read_text(encoding="utf-8"))
    if summary.get("failure_count") != 0:
        raise RuntimeError("PILOT_SUMMARY_HAS_FAILURES")
    if summary.get("athlete_count_completed") != 1:
        raise RuntimeError("PILOT_SUMMARY_COUNT_MISMATCH")
    athlete = json.loads((OUTPUT / "2932097" / "latest.json").read_text(encoding="utf-8"))
    if athlete.get("athlete_id") != 2932097 or athlete.get("as_of") != as_of:
        raise RuntimeError("PILOT_ATHLETE_RESULT_MISMATCH")
    if athlete.get("trainingpeaks_writes") != 0:
        raise RuntimeError("PILOT_WRITE_GUARD_FAILED")
    return {
        "athlete_id": 2932097,
        "status": athlete.get("status"),
        "alert_count": len(athlete.get("alerts") or []),
        "trainingpeaks_writes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    schedules = asyncio.run(verify_deployment_schedules())
    run_id = asyncio.run(create_run(args.as_of))
    state = wait(run_id)
    result = verify_files(args.as_of)
    print("COACHING_RADAR_V2_PILOT_RUN_PASS")
    print(json.dumps({
        "deployment": DEPLOYMENT,
        "flow_run_id": run_id,
        "state": state,
        **schedules,
        **result,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
