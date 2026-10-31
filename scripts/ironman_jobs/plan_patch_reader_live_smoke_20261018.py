"""Read-only E2E smoke on the existing private [MCP TEST] Training Plan.

It does not write workouts, notes, library items, accounts, or metadata.
"""
from __future__ import annotations

import asyncio
import json

from tp_mcp.client import TPClient

try:
    from scripts.ironman_jobs.plan_patch_batch_core import require
    from scripts.ironman_jobs.tp_plan_readonly_gateway import TrainingPeaksPlanReadGateway
except ModuleNotFoundError:
    from plan_patch_batch_core import require
    from tp_plan_readonly_gateway import TrainingPeaksPlanReadGateway


LAB = 684206
WINDOWS = [("2027-06-18", "2027-07-04")]


async def main() -> None:
    async with TPClient() as client:
        gateway = TrainingPeaksPlanReadGateway(client, LAB, WINDOWS)
        owner = await gateway.get_owner_id()
        plan = await gateway.get_plan(LAB)
        require(str(plan.get("title", "")).startswith("[MCP TEST]"),
                "LAB_TITLE_CHANGED")
        require(plan.get("isPublic") is False, "LAB_PLAN_NO_LONGER_PRIVATE")
        require(plan.get("workoutCount") == 6, "LAB_COUNT_CHANGED")
        rows = await gateway.list_workouts()
        require(len(rows) == 6, "LAB_WORKOUT_READ_NOT_6")
        ids = [row["workoutId"] for row in rows]
        require(len(set(ids)) == 6, "LAB_DUPLICATE_ID")
        verified = await gateway.get_workout(LAB, ids[0])
        require(verified.get("workoutId") == ids[0], "WORKOUT_DETAIL_READ_FAILED")
        print(json.dumps({
            "stage": "RELIABLE_PLAN_READER_PROVIDER_SMOKE_PASS",
            "owner": owner,
            "lab": LAB,
            "workout_count": len(rows),
            "first_workout_readback": ids[0],
            "public": False,
            "provider_writes": 0
        }), flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        # Operator captures stdout, not stderr. Expose a bounded, non-sensitive
        # failure classification so an import/runtime issue is diagnosable.
        print(json.dumps({"stage": "READER_LAB_STOP",
                          "kind": type(exc).__name__,
                          "reason": str(exc)[:160] if type(exc).__name__ == "PlanPatchStop" else "runtime_error",
                          "provider_writes": 0}), flush=True)
        raise SystemExit(93) from exc
