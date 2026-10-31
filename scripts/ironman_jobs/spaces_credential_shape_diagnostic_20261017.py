"""Safe Spaces credential-shape diagnostic.
Prints only lengths and coarse character-class properties; never credential bytes.
"""
from __future__ import annotations
import json
from tp_mcp.tools.assets import _secure_config

def shape(value: str) -> dict:
    return {
        "length": len(value),
        "ascii": value.isascii(),
        "alnum": value.isalnum(),
        "has_whitespace": any(ch.isspace() for ch in value),
    }

def main() -> int:
    cfg=_secure_config()
    out={
        "access_key_id": shape(cfg["access_key_id"]),
        "secret_access_key": shape(cfg["secret_access_key"]),
        "bucket": cfg["bucket"],
        "region": cfg["region"],
    }
    print("SPACES_CREDENTIAL_SHAPE")
    print(json.dumps(out, sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
