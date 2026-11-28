"""Read the latest Prefect admin-channel result stored on the TP droplet."""
from __future__ import annotations

import json
from pathlib import Path

LATEST = Path("/home/ironman/.local/state/ironman-prefect-admin-results/latest.json")


def main() -> int:
    if not LATEST.exists():
        print("PREFECT_ADMIN_RESULT_NONE")
        print(json.dumps({"found": False, "trainingpeaks_writes": 0}))
        return 0
    payload = json.loads(LATEST.read_text(encoding="utf-8"))
    if payload.get("schema") != "IRONMAN_PREFECT_ADMIN_RESULT_V1":
        raise RuntimeError("PREFECT_ADMIN_RESULT_SCHEMA_INVALID")
    if payload.get("trainingpeaks_writes") != 0:
        raise RuntimeError("PREFECT_ADMIN_RESULT_WRITE_GUARD_FAILED")
    print("PREFECT_ADMIN_RESULT_READ_PASS")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
