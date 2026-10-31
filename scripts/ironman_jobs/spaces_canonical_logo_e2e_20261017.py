"""Verified E2E canary upload from the canonical Drive logo master."""
import asyncio, json
from tp_mcp.tools.assets import tp_publish_public_asset

SOURCE_URL="https://sdmntprukwest.oaiusercontent.com/files/00000000-d390-8243-b3d6-2c8bd4e35abb/raw?se=2026-10-17T20%3A18%3A01Z&sp=r&sv=2026-02-06&sr=b&scid=e06b667d-d37b-5c71-8ed2-d827575de4c0&skoid=b5d2651b-fef3-4bb0-a03b-ca59cc22929b&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-10-17T19%3A37%3A58Z&ske=2026-10-18T19%3A37%3A58Z&sks=b&skv=2026-02-06&sig=BLLUI2N9Lmlz5OO4EjGQYpi%2BIiN57uTdXJIVOwjNgxQ%3D"
OBJECT_KEY="shared/canary/alberto-fazi-endurance-logo-master-v1.0.png"
EXPECTED_SIZE=352781
EXPECTED_SHA256="ad2710edac3834c467331d2497716c45f8e4cdaf37eaeb658203d531ea9ceea6"

async def run():
    result=await tp_publish_public_asset(SOURCE_URL,OBJECT_KEY,"image/png")
    if result.get("isError"):
        print(json.dumps(result,sort_keys=True))
        return 2
    if result.get("bytes")!=EXPECTED_SIZE or result.get("sha256")!=EXPECTED_SHA256:
        raise RuntimeError("uploaded_asset_mismatch")
    if result.get("public_readback")!="PASS":
        raise RuntimeError("public_readback_not_pass")
    print("SPACES_CANONICAL_LOGO_E2E_PASS")
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(run()))
