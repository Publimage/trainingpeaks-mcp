"""Read-only audit of the latest persisted Coaching Radar result on the TP droplet."""
from __future__ import annotations

import asyncio
import json

from tp_mcp.tools.radar import tp_get_coaching_radar

ATHLETE_ID = "2932097"


def main() -> int:
    result = asyncio.run(tp_get_coaching_radar(ATHLETE_ID))
    if result.get("isError"):
        print("COACHING_RADAR_RESULT_NOT_READY")
        print(json.dumps(result, ensure_ascii=False))
        return 2
    if result.get("schema") != "IRONMAN_COACHING_RADAR_V1":
        raise RuntimeError("RADAR_SCHEMA_MISMATCH")
    if str(result.get("athlete_id")) != ATHLETE_ID:
        raise RuntimeError("RADAR_ATHLETE_MISMATCH")
    if result.get("trainingpeaks_writes") != 0:
        raise RuntimeError("RADAR_WRITE_GUARD_FAILED")
    print("COACHING_RADAR_RESULT_AUDIT_PASS")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
