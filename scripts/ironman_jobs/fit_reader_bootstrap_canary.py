"""Install the pinned FIT decoder and prove live read-only decoding on Silvia.

Local server environment mutation only: installs fitdecode==0.11.0 in the
existing MCP venv. TrainingPeaks operations in this canary are GET-only.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from importlib.util import find_spec

FITDECODE_PIN = "fitdecode==0.11.0"
ATHLETE_ID = "4480273"
TARGETS = [
    ("swim", "4007650256", "1390842733"),
    ("bike", "4007654126", "-2008836994"),
    ("run", "4007650672", "1740953577"),
]


def ensure_fitdecode() -> None:
    if find_spec("fitdecode") is not None:
        return
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            FITDECODE_PIN,
        ],
        check=True,
    )


async def main() -> int:
    ensure_fitdecode()
    from tp_mcp.client.context import athlete_override
    from tp_mcp.tools.fit_reader import tp_get_workout_fit_data

    token = athlete_override.set(ATHLETE_ID)
    try:
        report = []
        for sport, workout_id, file_id in TARGETS:
            result = await tp_get_workout_fit_data(
                workout_id=workout_id,
                file_id=file_id,
                sample_seconds=30,
                max_records=1000,
            )
            if result.get("isError"):
                raise RuntimeError(f"{sport} FIT read failed: {result}")
            if result.get("record_count_raw", 0) <= 0:
                raise RuntimeError(f"{sport} FIT decoded with no record messages")
            report.append(
                {
                    "sport": sport,
                    "workout_id": workout_id,
                    "file_id": file_id,
                    "record_count_raw": result["record_count_raw"],
                    "returned_records": len(result["records"]),
                    "fields": result["record_fields"],
                    "sessions": len(result["sessions"]),
                    "laps": len(result["laps"]),
                    "lengths": len(result["lengths"]),
                }
            )
        print("FIT_CANARY_PASS")
        print(json.dumps(report, ensure_ascii=False))
        return 0
    finally:
        athlete_override.reset(token)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
