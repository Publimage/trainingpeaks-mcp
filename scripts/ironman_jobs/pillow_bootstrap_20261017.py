"""Install pinned Pillow into the existing MCP runtime venv and verify import/version.
Local server environment mutation only. No provider writes.
"""
from __future__ import annotations
import json, subprocess, sys
from importlib.util import find_spec

PIN="Pillow==11.3.0"

def ensure_pillow() -> str:
    if find_spec("PIL") is None:
        subprocess.run(
            [sys.executable,"-m","pip","install","--disable-pip-version-check","--no-input",PIN],
            check=True,
        )
    from PIL import __version__ as version
    if version != "11.3.0":
        raise RuntimeError(f"unexpected_pillow_version:{version}")
    return version

def main() -> int:
    version=ensure_pillow()
    print("PILLOW_BOOTSTRAP_PASS")
    print(json.dumps({"version":version,"pin":PIN},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
