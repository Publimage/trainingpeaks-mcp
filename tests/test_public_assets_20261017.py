from datetime import datetime, timezone

import pytest

from tp_mcp.tools.assets import (
    _signed_put_headers,
    _validate_object_key,
    _validate_source_url,
)


def test_asset_object_key_policy():
    assert _validate_object_key("brand/logo/alberto-fazi-endurance-logo-v1.0.png")
    assert _validate_object_key("trainingpeaks/first-ironman-24w/hero-v1.webp")
    with pytest.raises(ValueError):
        _validate_object_key("../secret")
    with pytest.raises(ValueError):
        _validate_object_key("other/file.png")


def test_asset_source_host_policy():
    assert _validate_source_url("https://example.oaiusercontent.com/path/file.png")
    with pytest.raises(ValueError):
        _validate_source_url("http://example.oaiusercontent.com/file.png")
    with pytest.raises(ValueError):
        _validate_source_url("https://example.com/file.png")


def test_sigv4_headers_are_deterministic():
    headers = _signed_put_headers(
        access_key="AKIDEXAMPLE",
        secret_key="secret-example",
        region="fra1",
        host="ironman-assets.fra1.digitaloceanspaces.com",
        object_key="brand/logo/test.png",
        content_type="image/png",
        payload_sha256="0" * 64,
        now=datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert headers["x-amz-date"] == "20261017T120000Z"
    assert headers["Authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20261017/fra1/s3/aws4_request"
    )
    assert "Signature=" in headers["Authorization"]
