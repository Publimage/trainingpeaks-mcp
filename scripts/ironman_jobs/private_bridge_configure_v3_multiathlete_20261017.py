"""Expand private bridge allowlist to the active Alberto Coaching Radar roster."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG = Path("/home/ironman/.config/ironman/private_bridge.json")
EXPECTED = {
    "host": "10.114.0.2",
    "port": 8787,
    "allowed_sources": ["10.114.0.2", "10.114.0.3"],
    "allowed_athletes": [
        "6133559",
        "3657374",
        "5590716",
        "5976093",
        "4732548",
        "6605664",
        "2932097",
        "6583514",
        "6610602",
        "4480273"
    ],
    "result_writer_sources": ["10.114.0.3"],
    "max_window_days": 21,
}


def main() -> int:
    if not CONFIG.exists():
        raise RuntimeError("BRIDGE_CONFIG_MISSING")
    current = json.loads(CONFIG.read_text(encoding="utf-8"))
    for key in ("host", "port", "allowed_sources", "result_writer_sources", "max_window_days"):
        if current.get(key) != EXPECTED[key]:
            raise RuntimeError(f"BRIDGE_CONFIG_UNEXPECTED:{key}")
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG.parent, 0o700)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(EXPECTED, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG)
    os.chmod(CONFIG, 0o600)
    readback = json.loads(CONFIG.read_text(encoding="utf-8"))
    if readback != EXPECTED:
        raise RuntimeError("BRIDGE_CONFIG_V3_READBACK_MISMATCH")
    print("PRIVATE_BRIDGE_CONFIG_V3_MULTIATHLETE_PASS")
    print(json.dumps({
        "athlete_count": len(EXPECTED["allowed_athletes"]),
        "allowed_athletes": EXPECTED["allowed_athletes"],
        "provider_writes": 0
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
