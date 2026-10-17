"""One-shot verified upload of the approved Alberto Fazi Endurance web logo."""
import asyncio, json
from tp_mcp.tools.assets import tp_publish_public_asset

SOURCE_URL="https://sdmntprpolandcentral.oaiusercontent.com/files/00000000-96c4-820a-978b-082d6910e505/raw?se=2026-10-17T19%3A02%3A08Z&sp=r&sv=2026-02-06&sr=b&scid=91235f7f-0b92-5457-8da6-fa99ec88df3c&skoid=b5d2651b-fef3-4bb0-a03b-ca59cc22929b&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-10-17T04%3A10%3A34Z&ske=2026-10-18T04%3A10%3A34Z&sks=b&skv=2026-02-06&sig=5Eyjo2qs6p/T1dwMjKYrKcjgcJdu9lanilEQnP5Qyws%3D"
OBJECT_KEY="brand/logo/alberto-fazi-endurance-logo-v1.0.png"
EXPECTED_SIZE=112958
EXPECTED_SHA256="3960fee00da0596141c64ffa3b554d6d9478baea212cec3440795d6275e360ab"

async def run():
    result=await tp_publish_public_asset(SOURCE_URL,OBJECT_KEY,"image/png")
    if result.get("isError"):
        print(json.dumps(result,sort_keys=True))
        return 2
    if result.get("bytes")!=EXPECTED_SIZE or result.get("sha256")!=EXPECTED_SHA256:
        raise RuntimeError("uploaded_asset_mismatch")
    if result.get("public_readback")!="PASS":
        raise RuntimeError("public_readback_not_pass")
    print("SPACES_ASSET_UPLOADER_E2E_PASS")
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(run()))
