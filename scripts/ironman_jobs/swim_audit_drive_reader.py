"""Read a canonical swim record as exact Google Drive plain text, not Markdown.

Pass an already authorized, read-only Google session. This module does not
load credentials, copy secrets, write providers or attest session authenticity.
It implements the acquisition adapter's read_document(spec) interface without
changing the existing Radar reader. Markdown export escapes JSON and markers.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
EXPORT_MIME = "text/plain"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
try:
    from requests.exceptions import ConnectionError as RequestsConnectionError
    from requests.exceptions import Timeout as RequestsTimeout
except ImportError:
    TRANSPORT_ERRORS = (TimeoutError, ConnectionError)
else:
    TRANSPORT_ERRORS = (TimeoutError, ConnectionError, RequestsConnectionError, RequestsTimeout)


class GoogleDriveSwimSourceReader:
    """GET only; metadata before/after export detects observed version drift.

    Two matching reads are not an atomic lock or proof against later changes.
    The caller must still validate the independent reviewed record digest.
    """

    def __init__(self, session: Any, *, now_fn=None):
        self._session = session
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def _get(self, url: str):
        try:
            response = self._session.get(url, timeout=30, allow_redirects=False)
        except TRANSPORT_ERRORS:
            # Acquisition retries typed transport failures, not error prose.
            raise ConnectionError("SWIM_DRIVE_TRANSPORT_UNAVAILABLE") from None
        status = getattr(response, "status_code", None)
        if status in (401, 403):
            raise PermissionError("SWIM_DRIVE_ACCESS_DENIED")
        if status in (500, 502, 503, 504):
            raise ConnectionError("SWIM_DRIVE_TEMPORARY_HTTP_FAILURE")
        if status != 200:
            # Includes redirects and quota/rate limits: no guessed alternate URL.
            raise RuntimeError("SWIM_DRIVE_HTTP_REJECTED")
        return response

    def _metadata(self, url: str, spec: Any) -> dict:
        response = self._get(url)
        try:
            meta = response.json()
        except (ValueError, TypeError):
            raise RuntimeError("SWIM_DRIVE_METADATA_INVALID") from None
        if type(meta) is not dict:
            raise RuntimeError("SWIM_DRIVE_METADATA_INVALID")
        if meta.get("id") != spec.document_id or meta.get("name") != spec.expected_title:
            raise RuntimeError("SWIM_DRIVE_IDENTITY_MISMATCH")
        if meta.get("mimeType") != GOOGLE_DOC_MIME or meta.get("trashed") is not False:
            raise RuntimeError("SWIM_DRIVE_DOCUMENT_UNAVAILABLE")
        version = meta.get("version")
        if type(version) is not str or re.fullmatch(r"[0-9]+", version) is None:
            raise RuntimeError("SWIM_DRIVE_VERSION_MISSING")
        return meta

    def read_document(self, spec: Any) -> tuple[dict[str, Any], str]:
        document_id = getattr(spec, "document_id", None)
        title = getattr(spec, "expected_title", None)
        if (type(document_id) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{10,200}", document_id) is None
                or type(title) is not str or not title or title.strip() != title
                or getattr(spec, "role", None) != "swim_audit_prescription"):
            raise ValueError("SWIM_DRIVE_SPEC_INVALID")
        base = "https://www.googleapis.com/drive/v3/files/" + quote(document_id, safe="")
        meta_url = base + "?fields=id,name,mimeType,version,modifiedTime,trashed"
        before = self._metadata(meta_url, spec)
        response = self._get(base + "/export?mimeType=" + quote(EXPORT_MIME, safe=""))
        raw = response.content
        if type(raw) is not bytes or not raw or len(raw) > MAX_DOCUMENT_BYTES:
            raise RuntimeError("SWIM_DRIVE_CONTENT_SIZE_INVALID")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise RuntimeError("SWIM_DRIVE_CONTENT_NOT_UTF8") from None
        after = self._metadata(meta_url, spec)
        if (before["version"] != after["version"]
                or before.get("modifiedTime") != after.get("modifiedTime")):
            raise RuntimeError("SWIM_DRIVE_CHANGED_DURING_EXPORT")
        now = self._now_fn()
        if not isinstance(now, datetime) or now.utcoffset() is None:
            raise ValueError("SWIM_DRIVE_CLOCK_INVALID")
        return {
            "title": before["name"], "document_id": before["id"],
            "source_version": before["version"], "version_kind": "DRIVE_FILE_VERSION",
            "modified_time": before.get("modifiedTime"),
            "retrieved_at_utc": now.astimezone(timezone.utc).isoformat(),
            "content_sha256": hashlib.sha256(raw).hexdigest(), "source": "GOOGLE_DRIVE",
        }, text
