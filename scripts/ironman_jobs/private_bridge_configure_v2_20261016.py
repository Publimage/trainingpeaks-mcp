"""Upgrade private bridge config with the Prefect-only result writer."""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG = Path("/home/ironman/.config/ironman/private_bridge.json")
EXPECTED = {
    "host": "10.114.0.2",
    "port": 8787,
    "allowed_sources": ["10.114.0.2", "10.114.0.3"],
    "allowed_athletes": ["2932097"],
    "result_writer_sources": ["10.114.0.3"],
    "max_window_days": 21,
}


def main() -> int:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG.parent, 0o700)
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(EXPECTED, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG)
    os.chmod(CONFIG, 0o600)
    if json.loads(CONFIG.read_text(encoding="utf-8")) != EXPECTED:
        raise RuntimeError("BRIDGE_CONFIG_V2_READBACK_MISMATCH")
    print("PRIVATE_BRIDGE_CONFIG_V2_PASS")
    print(json.dumps({"path": str(CONFIG), "provider_writes": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
