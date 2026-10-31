"""One-shot verified upload of the approved Alberto Fazi Endurance web logo."""
import asyncio, json
from tp_mcp.tools.assets import tp_publish_public_asset

SOURCE_URL="https://sdmntprpolandcentral.oaiusercontent.com/files/00000000-1a70-820a-853c-b8d96258814c/raw?se=2026-10-17T19%3A18%3A24Z&sp=r&sv=2026-02-06&sr=b&scid=0e51cbd9-ed16-56c1-b65c-f916aa70dae8&skoid=b5d2651b-fef3-4bb0-a03b-ca59cc22929b&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-10-16T20%3A45%3A38Z&ske=2026-10-17T20%3A45%3A38Z&sks=b&skv=2026-02-06&sig=HWdLQNCKWtgt4fzT6iPpZ7QHT8/Iz9/u7/MHyI%2Bq6O0%3D"
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
