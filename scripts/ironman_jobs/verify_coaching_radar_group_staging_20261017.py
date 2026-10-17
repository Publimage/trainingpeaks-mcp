"""Create exactly one multi-athlete Radar run and verify all active roster outputs."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from uuid import UUID

from prefect.client.orchestration import get_client

DEPLOYMENT = "ironman-coaching-radar-v2/alberto-group-readonly-daily"
ROSTER = Path("/opt/ironman-prefect/radar-src/data/coaching_radar_alberto_group_v1.json")
OUTPUT = Path("/var/lib/ironman-prefect/radar")


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


def wait(run_id: str, timeout: int = 600) -> str:
    end = time.monotonic() + timeout
    last = "UNKNOWN"
    while time.monotonic() < end:
        last = asyncio.run(read_state(run_id))
        if last == "COMPLETED":
            return last
        if last in {"FAILED", "CRASHED", "CANCELLED"}:
            raise RuntimeError(f"GROUP_RADAR_FLOW_FAILED:{last}")
        time.sleep(3)
    raise RuntimeError(f"GROUP_RADAR_FLOW_TIMEOUT:{last}")


def verify_files(as_of: str) -> dict:
    roster_raw = json.loads(ROSTER.read_text(encoding="utf-8"))
    ids = [int(x["athlete_id"]) for x in roster_raw["athletes"] if x.get("enabled")]
    summary_path = OUTPUT / "group_74397" / f"summary_{as_of}.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("failure_count") != 0:
        raise RuntimeError("GROUP_SUMMARY_HAS_FAILURES")
    if summary.get("athlete_count_completed") != len(ids):
        raise RuntimeError("GROUP_SUMMARY_COUNT_MISMATCH")
    missing = []
    for athlete_id in ids:
        path = OUTPUT / str(athlete_id) / "latest.json"
        if not path.exists():
            missing.append(athlete_id)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("trainingpeaks_writes") != 0 or payload.get("as_of") != as_of:
            raise RuntimeError(f"ATHLETE_RESULT_GUARD_FAILED:{athlete_id}")
    if missing:
        raise RuntimeError(f"ATHLETE_RESULTS_MISSING:{missing}")
    return {
        "athlete_count": len(ids),
        "status_counts": summary.get("status_counts"),
        "trainingpeaks_writes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    run_id = asyncio.run(create_run(args.as_of))
    state = wait(run_id)
    files = verify_files(args.as_of)
    print("COACHING_RADAR_GROUP_PREFECT_RUN_PASS")
    print(json.dumps({
        "deployment": DEPLOYMENT,
        "flow_run_id": run_id,
        "state": state,
        **files,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
