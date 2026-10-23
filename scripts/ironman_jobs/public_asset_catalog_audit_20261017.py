"""Read-only catalog audit for the IRONMAN public asset publisher."""
from tp_mcp.tools.assets import (
    CONFIG_PATH,
    EXPECTED_BUCKET,
    EXPECTED_PUBLIC_HOST,
    tp_publish_public_asset,
)


def main() -> int:
    assert callable(tp_publish_public_asset)
    assert EXPECTED_BUCKET == "ironman-assets"
    assert EXPECTED_PUBLIC_HOST == "ironman-assets.fra1.digitaloceanspaces.com"
    print("IRONMAN_PUBLIC_ASSET_CATALOG_PASS")
    print(f"config_path={CONFIG_PATH}")
    print("provider_writes=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
