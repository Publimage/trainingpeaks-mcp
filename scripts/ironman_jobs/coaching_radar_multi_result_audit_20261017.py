"""Read-only audit of latest Coaching Radar results for the active Alberto roster."""
from __future__ import annotations

import asyncio
import json

from tp_mcp.tools.radar import tp_get_coaching_radar

ATHLETES = {
    "6133559": "Cesare Bertuccelli",
    "3657374": "Eugenio Rossetti",
    "5590716": "Francesco Franceschini",
    "5976093": "Gianluca Gregorini",
    "4732548": "Giuseppe Giannoni",
    "6605664": "Lorenzo Notaro",
    "2932097": "Massimiliano Polverari",
    "6583514": "Michele Manfredi",
    "6610602": "Samuele Ascenzi",
    "4480273": "Silvia Moglioni",
}


async def audit() -> dict:
    results = []
    failures = []
    for athlete_id, name in ATHLETES.items():
        payload = await tp_get_coaching_radar(athlete_id)
        if payload.get("isError"):
            failures.append({
                "athlete_id": int(athlete_id),
                "athlete_name": name,
                "error_code": payload.get("error_code"),
            })
            continue
        if str(payload.get("athlete_id")) != athlete_id:
            raise RuntimeError(f"RADAR_ATHLETE_MISMATCH:{athlete_id}")
        if payload.get("trainingpeaks_writes") != 0:
            raise RuntimeError(f"RADAR_WRITE_GUARD_FAILED:{athlete_id}")
        results.append({
            "athlete_id": int(athlete_id),
            "athlete_name": name,
            "as_of": payload.get("as_of"),
            "status": payload.get("status"),
            "alert_count": len(payload.get("alerts") or []),
            "evidence_sha256": payload.get("evidence_sha256"),
        })
    return {
        "schema": "IRONMAN_COACHING_RADAR_MULTI_READBACK_V1",
        "expected": len(ATHLETES),
        "found": len(results),
        "missing": len(failures),
        "results": results,
        "failures": failures,
        "trainingpeaks_writes": 0,
    }


def main() -> int:
    outcome = asyncio.run(audit())
    print("COACHING_RADAR_MULTI_RESULT_AUDIT")
    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if outcome["missing"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
