"""Create the approved 1200x400 web export from the Drive master and publish it."""
from __future__ import annotations
import asyncio, hashlib, io, json
import httpx
from PIL import Image
from tp_mcp.tools.assets import _secure_config, _signed_put_headers, _validate_object_key

SOURCE_URL="https://sdmntprpolandcentral.oaiusercontent.com/files/00000000-dcb8-820a-8930-9a0e1a955f6b/raw?se=2026-10-17T20%3A19%3A40Z&sp=r&sv=2026-02-06&sr=b&scid=10217c0b-7a34-5686-8518-484c722b72a9&skoid=b5d2651b-fef3-4bb0-a03b-ca59cc22929b&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-10-17T18%3A22%3A23Z&ske=2026-10-18T18%3A22%3A23Z&sks=b&skv=2026-02-06&sig=GcyKqpKzX/Y4fntmUoSksGYWSAfN0kGFdOg3rWLAUUk%3D"
MASTER_SIZE=352781
MASTER_SHA="ad2710edac3834c467331d2497716c45f8e4cdaf37eaeb658203d531ea9ceea6"
OBJECT_KEY="brand/logo/alberto-fazi-endurance-logo-v1.0.png"
EXPECTED_SIZE=112958
EXPECTED_SHA="3960fee00da0596141c64ffa3b554d6d9478baea212cec3440795d6275e360ab"

async def run():
    cfg=_secure_config()
    key=_validate_object_key(OBJECT_KEY)
    public_url=f"https://{cfg['public_host']}/{key}"
    async with httpx.AsyncClient(follow_redirects=True,timeout=45.0) as client:
        src=await client.get(SOURCE_URL); src.raise_for_status()
        master=src.content
        if len(master)!=MASTER_SIZE or hashlib.sha256(master).hexdigest()!=MASTER_SHA:
            raise RuntimeError("master_mismatch")
        im=Image.open(io.BytesIO(master)).convert("RGBA")
        out=io.BytesIO()
        im.resize((1200,400),Image.Resampling.LANCZOS).save(out,format="PNG",optimize=True)
        data=out.getvalue()
        digest=hashlib.sha256(data).hexdigest()
        if len(data)!=EXPECTED_SIZE or digest!=EXPECTED_SHA:
            raise RuntimeError(f"derived_mismatch:{len(data)}:{digest}")
        existing=await client.get(public_url)
        if existing.status_code==200:
            ed=hashlib.sha256(existing.content).hexdigest()
            if ed!=digest:
                raise RuntimeError("target_exists_different")
            print("SPACES_BRAND_LOGO_PRODUCTION_PASS")
            print(json.dumps({"status":"ALREADY_PRESENT_VERIFIED","public_url":public_url,"bytes":len(data),"sha256":digest},sort_keys=True))
            return 0
        if existing.status_code not in (403,404):
            raise RuntimeError(f"existence_http_{existing.status_code}")
        headers=_signed_put_headers(access_key=cfg["access_key_id"],secret_key=cfg["secret_access_key"],region=cfg["region"],host=cfg["public_host"],object_key=key,content_type="image/png",payload_sha256=digest)
        put=await client.put(public_url,content=data,headers=headers)
        if put.status_code not in (200,201,204):
            raise RuntimeError(f"put_http_{put.status_code}")
        rb=await client.get(public_url)
        if rb.status_code!=200 or hashlib.sha256(rb.content).hexdigest()!=digest:
            raise RuntimeError("public_readback_failed")
    print("SPACES_BRAND_LOGO_PRODUCTION_PASS")
    print(json.dumps({"status":"UPLOADED_VERIFIED","public_url":public_url,"bytes":len(data),"sha256":digest},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(asyncio.run(run()))
