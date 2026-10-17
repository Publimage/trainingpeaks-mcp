from datetime import datetime, timezone

import pytest

from scripts.ironman_jobs.coaching_radar_drive_context_adapter_v0 import (
    ContextDocumentSpec,
    DRIVE_READONLY_SCOPE,
    GoogleDriveContextReader,
)


NOW = datetime(2026, 10, 17, 10, 30, tzinfo=timezone.utc)


class Response:
    def __init__(self, status_code=200, *, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        return self._payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, timeout):
        assert timeout == 30
        self.urls.append(url)
        return self.responses.pop(0)


def _spec():
    return ContextDocumentSpec("core_index", "doc123", "00_IRONMAN_CORE_INDEX")


def _meta(**overrides):
    value = {
        "id": "doc123",
        "name": "00_IRONMAN_CORE_INDEX",
        "mimeType": "application/vnd.google-apps.document",
        "version": "812",
        "modifiedTime": "2026-10-17T09:00:00Z",
        "trashed": False,
    }
    value.update(overrides)
    return value


def test_reader_returns_versioned_sha256_entry_and_markdown():
    session = Session([
        Response(payload=_meta()),
        Response(content=b"# Core\nCanonical text\n"),
    ])
    reader = GoogleDriveContextReader(session, now_fn=lambda: NOW)
    entry, content = reader.read_document(_spec())
    assert entry["source"] == "GOOGLE_DRIVE"
    assert entry["version_kind"] == "DRIVE_FILE_VERSION"
    assert entry["source_version"] == "812"
    assert len(entry["content_sha256"]) == 64
    assert entry["retrieved_at_utc"] == NOW.isoformat()
    assert content.startswith("# Core")
    assert "/export?mimeType=text%2Fmarkdown" in session.urls[1]


def test_reader_fails_on_title_mismatch_before_export():
    session = Session([Response(payload=_meta(name="WRONG"))])
    with pytest.raises(RuntimeError, match="KB_DRIVE_DOCUMENT_TITLE_MISMATCH"):
        GoogleDriveContextReader(session, now_fn=lambda: NOW).read_document(_spec())
    assert len(session.urls) == 1


def test_reader_fails_on_non_doc():
    session = Session([Response(payload=_meta(mimeType="application/pdf"))])
    with pytest.raises(RuntimeError, match="KB_DRIVE_DOCUMENT_MIME_MISMATCH"):
        GoogleDriveContextReader(session, now_fn=lambda: NOW).read_document(_spec())


def test_reader_fails_on_missing_version():
    session = Session([Response(payload=_meta(version=None))])
    with pytest.raises(RuntimeError, match="KB_DRIVE_VERSION_MISSING"):
        GoogleDriveContextReader(session, now_fn=lambda: NOW).read_document(_spec())


def test_reader_fails_on_http_error():
    session = Session([Response(status_code=403)])
    with pytest.raises(RuntimeError, match="KB_DRIVE_HTTP_403"):
        GoogleDriveContextReader(session, now_fn=lambda: NOW).read_document(_spec())


def test_reader_fails_on_empty_content():
    session = Session([Response(payload=_meta()), Response(content=b"")])
    with pytest.raises(RuntimeError, match="KB_DRIVE_DOCUMENT_EMPTY"):
        GoogleDriveContextReader(session, now_fn=lambda: NOW).read_document(_spec())


def test_scope_is_strict_read_only():
    assert DRIVE_READONLY_SCOPE == "https://www.googleapis.com/auth/drive.readonly"
