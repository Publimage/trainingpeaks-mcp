"""Static/local audit for the private Prefect admin result sink."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import tp_mcp.private_bridge as bridge


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="prefect-admin-sink-") as tmp:
        original = bridge.ADMIN_RESULT_DIR
        bridge.ADMIN_RESULT_DIR = Path(tmp)
        try:
            result = bridge._persist_admin_result(
                {
                    "schema": "IRONMAN_PREFECT_ADMIN_RESULT_V1",
                    "job_id": "bootstrap-status-20261016-001",
                    "operation": "status",
                    "state": "COMPLETED",
                    "source_host": "ironman-prefect-staging",
                    "started_at_utc": "2026-10-16T20:00:00+00:00",
                    "finished_at_utc": "2026-10-16T20:00:01+00:00",
                    "exit_code": 0,
                    "revision": None,
                    "details": {"prefect_server": "active"},
                    "output": "ok",
                    "trainingpeaks_writes": 0,
                },
                {"allowed_athletes": {"2932097"}},
            )
            latest = json.loads((Path(tmp) / "latest.json").read_text())
        finally:
            bridge.ADMIN_RESULT_DIR = original
    if not result.get("stored") or latest.get("operation") != "status":
        raise RuntimeError("PREFECT_ADMIN_SINK_LOCAL_AUDIT_FAILED")
    print("PREFECT_ADMIN_SINK_LOCAL_AUDIT_PASS")
    print(json.dumps({"stored": True, "trainingpeaks_writes": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
