"""Print a non-secret fingerprint of the configured Spaces access key ID.

Never prints the secret. Access key IDs are identifiers, but this diagnostic
still reveals only a short prefix/suffix and length to support safe comparison.
"""
import json
from tp_mcp.tools.assets import _secure_config

def main() -> int:
    cfg=_secure_config()
    key=cfg["access_key_id"]
    safe={
        "access_key_id_length": len(key),
        "access_key_id_prefix": key[:4],
        "access_key_id_suffix": key[-4:] if len(key) >= 4 else key,
        "contains_whitespace": any(ch.isspace() for ch in key),
    }
    print("SPACES_ACCESS_KEY_FINGERPRINT")
    print(json.dumps(safe, sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
