"""Read-only public check for the IRONMAN Spaces brand-logo canary."""
import hashlib, json, urllib.request, urllib.error

PUBLIC_URL = "https://ironman-assets.fra1.digitaloceanspaces.com/brand/logo/alberto-fazi-endurance-logo-v1.0.png"
EXPECTED_SIZE = 112958
EXPECTED_SHA256 = "3960fee00da0596141c64ffa3b554d6d9478baea212cec3440795d6275e360ab"

def main():
    try:
        with urllib.request.urlopen(PUBLIC_URL, timeout=30) as r:
            data=r.read()
            status=r.status
            headers=dict(r.headers.items())
    except urllib.error.HTTPError as e:
        print(json.dumps({"stage":"SPACES_ASSET_PUBLIC_CHECK","status":e.code,"exists":False}))
        return 0 if e.code in (403,404) else 2
    sha=hashlib.sha256(data).hexdigest()
    ok=status==200 and len(data)==EXPECTED_SIZE and sha==EXPECTED_SHA256
    print(json.dumps({"stage":"SPACES_ASSET_PUBLIC_CHECK","status":status,"exists":True,"size":len(data),"sha256":sha,"matches_expected":ok,"content_type":headers.get("Content-Type")}))
    return 0 if ok else 3

if __name__=="__main__":
    raise SystemExit(main())
