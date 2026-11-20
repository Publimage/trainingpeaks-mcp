import hashlib, json, urllib.request, urllib.error

SOURCE_URL = "https://sdmntprpolandcentral.oaiusercontent.com/files/00000000-e934-820a-b895-287a32dbe9d3/raw?se=2026-10-17T17%3A09%3A14Z&sp=r&sv=2026-02-06&sr=b&scid=9667964e-4636-515d-8b1b-438f84000c32&skoid=b5d2651b-fef3-4bb0-a03b-ca59cc22929b&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-10-17T05%3A14%3A40Z&ske=2026-10-18T05%3A14%3A40Z&sks=b&skv=2026-02-06&sig=4JcipXUgwNUxora6JfBnkfy3VNcySJkpEmjPQ93DdIE%3D"
PUT_URL = "https://ironman-assets.fra1.digitaloceanspaces.com/brand/logo/alberto-fazi-endurance-logo-v1.0.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=DO801DVXQYTLABLPMTPL%2F20261017%2Ffra1%2Fs3%2Faws4_request&X-Amz-Date=20261017T170421Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=cache-control%3Bcontent-type%3Bhost%3Bx-amz-acl&X-Amz-Signature=80f970f9adfbd4cef68cbbaaffa6cfec03a6d44512c9b417f4517ea520817e94"
PUBLIC_URL = "https://ironman-assets.fra1.digitaloceanspaces.com/brand/logo/alberto-fazi-endurance-logo-v1.0.png"
EXPECTED_SIZE = 112958
EXPECTED_SHA256 = "3960fee00da0596141c64ffa3b554d6d9478baea212cec3440795d6275e360ab"

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def validate(data: bytes) -> None:
    if len(data) != EXPECTED_SIZE:
        raise RuntimeError(f"size_mismatch:{len(data)}")
    if digest(data) != EXPECTED_SHA256:
        raise RuntimeError(f"sha256_mismatch:{digest(data)}")

def fetch_public():
    try:
        with urllib.request.urlopen(PUBLIC_URL, timeout=30) as r:
            data = r.read()
            return r.status, data, dict(r.headers.items())
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return e.code, b"", {}
        raise

def main():
    status, existing, headers = fetch_public()
    if status == 200:
        try:
            validate(existing)
            print(json.dumps({"stage":"SPACES_ASSET_UPLOAD_PASS","action":"already_present","url":PUBLIC_URL,"size":len(existing),"sha256":digest(existing)}))
            return
        except Exception:
            raise RuntimeError("target_exists_but_content_differs")

    with urllib.request.urlopen(SOURCE_URL, timeout=45) as r:
        source = r.read()
    validate(source)

    req = urllib.request.Request(PUT_URL, data=source, method="PUT", headers={
        "Content-Type":"image/png",
        "Cache-Control":"public, max-age=31536000, immutable",
        "x-amz-acl":"public-read",
    })
    with urllib.request.urlopen(req, timeout=45) as r:
        if r.status not in (200, 201, 204):
            raise RuntimeError(f"put_status:{r.status}")

    status2, final, headers2 = fetch_public()
    if status2 != 200:
        raise RuntimeError(f"public_read_status:{status2}")
    validate(final)
    print(json.dumps({
        "stage":"SPACES_ASSET_UPLOAD_PASS",
        "action":"uploaded",
        "url":PUBLIC_URL,
        "size":len(final),
        "sha256":digest(final),
        "content_type":headers2.get("Content-Type"),
        "cache_control":headers2.get("Cache-Control"),
    }))

if __name__ == "__main__":
    main()
