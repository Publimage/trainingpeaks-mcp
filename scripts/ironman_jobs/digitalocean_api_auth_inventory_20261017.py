"""Read-only DigitalOcean API credential presence diagnostic.
Never prints credential values.
"""
from __future__ import annotations
import json, os
from pathlib import Path

CANDIDATE_ENV = [
    "DIGITALOCEAN_TOKEN",
    "DIGITALOCEAN_ACCESS_TOKEN",
    "DO_API_TOKEN",
    "DO_TOKEN",
]
CANDIDATE_FILES = [
    "/home/ironman/.config/doctl/config.yaml",
    "/home/ironman/.config/digitalocean/token",
]

def main() -> int:
    result = {
        "env_present": {name: bool(os.environ.get(name)) for name in CANDIDATE_ENV},
        "files": [],
    }
    for raw in CANDIDATE_FILES:
        p=Path(raw)
        try:
            exists=p.exists()
            item={"path":raw,"exists":exists}
            if exists:
                st=p.stat()
                item.update({"mode":oct(st.st_mode & 0o777),"uid":st.st_uid,"gid":st.st_gid,"size":st.st_size})
        except OSError as exc:
            item={"path":raw,"exists":None,"error_type":type(exc).__name__}
        result["files"].append(item)
    print("DIGITALOCEAN_API_AUTH_INVENTORY")
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
