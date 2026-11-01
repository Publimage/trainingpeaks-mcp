"""Loopback-only staging entrypoint; never exposes a public socket by default."""
import os
import uvicorn

from inbound_api import create_runtime_app

if __name__ == "__main__":
    # Require operator-owned config, signed identity and explicit permissions.
    # TLS + trusted proxy/auth is required before any non-loopback exposure.
    if not os.environ.get("WG_CONFIG_PATH"):
        raise SystemExit("WG_CONFIG_PATH is required")
    uvicorn.run(create_runtime_app(), host="127.0.0.1", port=int(os.environ.get("WG_STAGING_PORT", "18765")),
                access_log=False, log_level="warning", workers=1)
