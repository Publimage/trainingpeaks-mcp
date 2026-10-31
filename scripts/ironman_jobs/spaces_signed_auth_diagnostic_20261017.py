"""Read-only signed-auth diagnostic for the IRONMAN Spaces uploader.

Never prints credentials. It signs an authenticated GET for a deliberately
nonexistent object. Expected healthy auth result is HTTP 404 NoSuchKey.
"""
from __future__ import annotations
import hashlib
import hmac
import json
from datetime import datetime, timezone
from urllib.parse import quote
import xml.etree.ElementTree as ET
import httpx

from tp_mcp.tools.assets import _secure_config, _signing_key

OBJECT_KEY="shared/__ironman_spaces_auth_probe_nonexistent__"

def signed_get_headers(cfg, key):
    now=datetime.now(timezone.utc)
    amz_date=now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp=now.strftime("%Y%m%d")
    host=cfg["public_host"]
    region=cfg["region"]
    payload_sha=hashlib.sha256(b"").hexdigest()
    canonical_uri="/"+quote(key,safe="/-_.~")
    canonical_headers=f"host:{host}\nx-amz-content-sha256:{payload_sha}\nx-amz-date:{amz_date}\n"
    signed_headers="host;x-amz-content-sha256;x-amz-date"
    canonical_request="\n".join(["GET",canonical_uri,"",canonical_headers,signed_headers,payload_sha])
    scope=f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign="\n".join(["AWS4-HMAC-SHA256",amz_date,scope,hashlib.sha256(canonical_request.encode()).hexdigest()])
    sig=hmac.new(_signing_key(cfg["secret_access_key"],date_stamp,region),string_to_sign.encode(),hashlib.sha256).hexdigest()
    return {
        "Host":host,
        "x-amz-content-sha256":payload_sha,
        "x-amz-date":amz_date,
        "Authorization":f"AWS4-HMAC-SHA256 Credential={cfg['access_key_id']}/{scope}, SignedHeaders={signed_headers}, Signature={sig}",
    }

def parse_xml(body):
    try:
        root=ET.fromstring(body)
        return {"code":root.findtext("Code"),"message":root.findtext("Message")}
    except Exception:
        return {"code":None,"message":None}

async def main_async():
    cfg=_secure_config()
    url=f"https://{cfg['public_host']}/{OBJECT_KEY}"
    headers=signed_get_headers(cfg,OBJECT_KEY)
    async with httpx.AsyncClient(timeout=30.0) as client:
        r=await client.get(url,headers=headers)
    safe={"status":r.status_code,"auth_probe":"signed_get_nonexistent_object",**parse_xml(r.text)}
    print("SPACES_SIGNED_AUTH_DIAGNOSTIC")
    print(json.dumps(safe,sort_keys=True))
    return 0 if r.status_code in (404,403) else 2

if __name__=="__main__":
    import asyncio
    raise SystemExit(asyncio.run(main_async()))
