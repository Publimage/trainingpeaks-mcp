"""Publish approved IRONMAN image assets to DigitalOcean Spaces.

The master asset remains in Google Drive. This module only accepts a temporary
HTTPS source URL, validates the image, uploads a versioned object to the single
approved Space, and performs an independent public readback.

Credentials live only in a root/service-managed local config file and are never
returned by the tool.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

CONFIG_PATH = Path("/home/ironman/.config/ironman/spaces-uploader.json")
EXPECTED_BUCKET = "ironman-assets"
EXPECTED_PUBLIC_HOST = "ironman-assets.fra1.digitaloceanspaces.com"
EXPECTED_REGION = "fra1"
MAX_BYTES = 10 * 1024 * 1024
ALLOWED_PREFIXES = ("brand/", "trainingpeaks/", "shared/", "web/")
ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}
ALLOWED_SOURCE_SUFFIXES = (".oaiusercontent.com", ".googleusercontent.com")
_OBJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _error(code: str, message: str) -> dict[str, Any]:
    return {"isError": True, "error_code": code, "message": message}


def _secure_config(path: Path = CONFIG_PATH) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError("SPACES_CONFIG_MISSING")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise RuntimeError(f"SPACES_CONFIG_PERMISSIONS_TOO_OPEN:{oct(mode)}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "bucket",
        "region",
        "public_host",
        "access_key_id",
        "secret_access_key",
    }
    missing = sorted(required - raw.keys())
    if missing:
        raise RuntimeError(f"SPACES_CONFIG_FIELDS_MISSING:{','.join(missing)}")
    if raw["bucket"] != EXPECTED_BUCKET:
        raise RuntimeError("SPACES_BUCKET_MISMATCH")
    if raw["region"] != EXPECTED_REGION:
        raise RuntimeError("SPACES_REGION_MISMATCH")
    if raw["public_host"] != EXPECTED_PUBLIC_HOST:
        raise RuntimeError("SPACES_PUBLIC_HOST_MISMATCH")
    return {key: str(value) for key, value in raw.items()}


def _validate_source_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        raise ValueError("SOURCE_URL_MUST_BE_HTTPS")
    if not any(host.endswith(suffix) for suffix in ALLOWED_SOURCE_SUFFIXES):
        raise ValueError("SOURCE_HOST_NOT_ALLOWED")
    return host


def _validate_object_key(object_key: str) -> str:
    value = object_key.strip()
    if value.startswith("/") or ".." in value.split("/"):
        raise ValueError("OBJECT_KEY_INVALID")
    if not _OBJECT_RE.fullmatch(value):
        raise ValueError("OBJECT_KEY_INVALID")
    if not value.startswith(ALLOWED_PREFIXES):
        raise ValueError("OBJECT_PREFIX_NOT_ALLOWED")
    if value.endswith("/"):
        raise ValueError("OBJECT_KEY_INVALID")
    return value


def _validate_content_type(content_type: str) -> str:
    value = content_type.lower().strip()
    if value not in ALLOWED_CONTENT_TYPES:
        raise ValueError("CONTENT_TYPE_NOT_ALLOWED")
    return value


def _signing_key(secret: str, date_stamp: str, region: str) -> bytes:
    k_date = hmac.new(("AWS4" + secret).encode(), date_stamp.encode(), hashlib.sha256).digest()
    k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_region, b"s3", hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


def _signed_put_headers(
    *,
    access_key: str,
    secret_key: str,
    region: str,
    host: str,
    object_key: str,
    content_type: str,
    payload_sha256: str,
    now: datetime | None = None,
) -> dict[str, str]:
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    canonical_uri = "/" + quote(object_key, safe="/-_.~")
    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        "x-amz-acl:public-read\n"
        f"x-amz-content-sha256:{payload_sha256}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "content-type;host;x-amz-acl;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        ["PUT", canonical_uri, "", canonical_headers, signed_headers, payload_sha256]
    )
    scope = f"{date_stamp}/{region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    signature = hmac.new(
        _signing_key(secret_key, date_stamp, region),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        "AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Content-Type": content_type,
        "Host": host,
        "x-amz-acl": "public-read",
        "x-amz-content-sha256": payload_sha256,
        "x-amz-date": amz_date,
        "Authorization": authorization,
    }


async def tp_publish_public_asset(
    source_url: str,
    object_key: str,
    content_type: str = "image/png",
) -> dict[str, Any]:
    """Publish one approved image without overwriting a different existing object."""
    try:
        _validate_source_url(source_url)
        key = _validate_object_key(object_key)
        mime = _validate_content_type(content_type)
        cfg = _secure_config()
    except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
        return _error("ASSET_PREFLIGHT_FAILED", str(exc))

    public_url = f"https://{cfg['public_host']}/{quote(key, safe='/-_.~')}"

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            source = await client.get(source_url)
            source.raise_for_status()
            data = source.content
            if not data or len(data) > MAX_BYTES:
                return _error("ASSET_SIZE_INVALID", f"bytes={len(data)}")
            digest = hashlib.sha256(data).hexdigest()

            # Immutable/versioned policy: existing different content is never overwritten.
            existing = await client.get(public_url)
            if existing.status_code == 200:
                existing_digest = hashlib.sha256(existing.content).hexdigest()
                if existing_digest != digest:
                    return _error(
                        "ASSET_ALREADY_EXISTS_DIFFERENT",
                        "Object key already exists with different bytes; use a new versioned filename.",
                    )
                return {
                    "schema": "IRONMAN_PUBLIC_ASSET_V1",
                    "status": "ALREADY_PRESENT_VERIFIED",
                    "object_key": key,
                    "public_url": public_url,
                    "content_type": mime,
                    "bytes": len(data),
                    "sha256": digest,
                    "public_readback": "PASS",
                }
            if existing.status_code not in (403, 404):
                return _error(
                    "ASSET_EXISTENCE_CHECK_FAILED",
                    f"public GET returned HTTP {existing.status_code}",
                )

            headers = _signed_put_headers(
                access_key=cfg["access_key_id"],
                secret_key=cfg["secret_access_key"],
                region=cfg["region"],
                host=cfg["public_host"],
                object_key=key,
                content_type=mime,
                payload_sha256=digest,
            )
            uploaded = await client.put(public_url, content=data, headers=headers)
            if uploaded.status_code not in (200, 201, 204):
                return _error(
                    "SPACES_UPLOAD_FAILED",
                    f"Spaces PUT returned HTTP {uploaded.status_code}",
                )

            readback = await client.get(public_url)
            if readback.status_code != 200:
                return _error(
                    "ASSET_READBACK_FAILED",
                    f"public GET returned HTTP {readback.status_code}",
                )
            readback_digest = hashlib.sha256(readback.content).hexdigest()
            if readback_digest != digest:
                return _error("ASSET_READBACK_HASH_MISMATCH", "Uploaded bytes differ from source.")

            return {
                "schema": "IRONMAN_PUBLIC_ASSET_V1",
                "status": "UPLOADED_VERIFIED",
                "object_key": key,
                "public_url": public_url,
                "content_type": mime,
                "bytes": len(data),
                "sha256": digest,
                "public_readback": "PASS",
            }
    except httpx.HTTPError as exc:
        return _error("ASSET_NETWORK_ERROR", f"{type(exc).__name__}: {exc}")


__all__ = [
    "tp_publish_public_asset",
    "_signed_put_headers",
    "_validate_object_key",
    "_validate_source_url",
]
