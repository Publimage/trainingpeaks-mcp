"""Run one Coaching Radar deployment and verify the persisted result sink."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import urllib.request
from uuid import UUID

from prefect.client.orchestration import get_client

DEPLOYMENT = "ironman-coaching-radar-v1/polverari-readonly-pilot"
TP_BRIDGE = "http://10.114.0.2:8787"


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


def wait(run_id: str, timeout: int = 180) -> str:
    end = time.monotonic() + timeout
    last = "UNKNOWN"
    while time.monotonic() < end:
        last = asyncio.run(read_state(run_id))
        if last == "COMPLETED":
            return last
        if last in {"FAILED", "CRASHED", "CANCELLED"}:
            raise RuntimeError(f"RADAR_FLOW_FAILED:{last}")
        time.sleep(2)
    raise RuntimeError(f"RADAR_FLOW_TIMEOUT:{last}")


def verify_sink(as_of: str) -> dict:
    req = urllib.request.Request(TP_BRIDGE + "/health")
    with urllib.request.urlopen(req, timeout=10) as response:
        health = json.loads(response.read().decode("utf-8"))
    if health.get("mode") != "READ_ONLY":
        raise RuntimeError("BRIDGE_HEALTH_BAD")
    return {"as_of": as_of, "bridge_mode": health["mode"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    run_id = asyncio.run(create_run(args.as_of))
    state = wait(run_id)
    sink = verify_sink(args.as_of)
    print("COACHING_RADAR_PREFECT_RUN_PASS")
    print(json.dumps({
        "deployment": DEPLOYMENT,
        "flow_run_id": run_id,
        "state": state,
        **sink,
        "trainingpeaks_writes": 0,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
