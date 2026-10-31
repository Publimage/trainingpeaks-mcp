"""Install the explicit private bridge config on ironman-tp-mcp.

Server-local configuration only. No TrainingPeaks provider writes.
"""
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
    "max_window_days": 21,
}


def main() -> int:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG.parent, 0o700)
    temp = CONFIG.with_suffix(".tmp")
    temp.write_text(json.dumps(EXPECTED, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(CONFIG)
    os.chmod(CONFIG, 0o600)
    loaded = json.loads(CONFIG.read_text(encoding="utf-8"))
    if loaded != EXPECTED:
        raise RuntimeError("BRIDGE_CONFIG_READBACK_MISMATCH")
    mode = oct(CONFIG.stat().st_mode & 0o777)
    if mode != "0o600":
        raise RuntimeError("BRIDGE_CONFIG_PERMISSIONS_MISMATCH")
    print("PRIVATE_BRIDGE_CONFIG_PASS")
    print(json.dumps({"path": str(CONFIG), "mode": mode, "provider_writes": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
