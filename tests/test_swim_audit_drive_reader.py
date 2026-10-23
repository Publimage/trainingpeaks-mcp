"""Synthetic HTTP boundary tests. No credentials or private source records."""
import copy
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.ironman_jobs.swim_audit_drive_reader import (
    GOOGLE_DOC_MIME, MAX_DOCUMENT_BYTES, GoogleDriveSwimSourceReader,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
SPEC = SimpleNamespace(role="swim_audit_prescription", document_id="synthetic_doc_1",
                       expected_title="Synthetic source")
META = dict(id=SPEC.document_id, name=SPEC.expected_title, mimeType=GOOGLE_DOC_MIME,
            version="7", modifiedTime="2026-01-01T00:00:00Z", trashed=False)
RAW = b'[SWIM_AUDIT_BEGIN:test_v1]\n{"a_b":[1]}\n[SWIM_AUDIT_END:test_v1]\n'


class Response:
    def __init__(self, data=None, raw=RAW, status=200):
        self.status_code = status
        self.content = raw
        self.data = copy.deepcopy(data)

    def json(self):
        return copy.deepcopy(self.data)


class Session:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_reader(*, raw=RAW, first=None, last=None):
    session = Session([Response(META if first is None else first), Response(raw=raw),
                       Response(META if last is None else last)])
    return GoogleDriveSwimSourceReader(session, now_fn=lambda: NOW), session


def test_exact_plain_text_transport_and_hash():
    reader, session = make_reader()
    entry, text = reader.read_document(SPEC)
    assert text.encode() == RAW
    assert entry["content_sha256"] == hashlib.sha256(RAW).hexdigest()
    assert entry["source_version"] == "7"
    assert entry["version_kind"] == "DRIVE_FILE_VERSION"
    assert entry["retrieved_at_utc"] == NOW.isoformat()
    assert len(session.calls) == 3
    assert session.calls[0][0] == session.calls[2][0]
    url = urlsplit(session.calls[1][0])
    assert url.scheme == "https" and url.netloc == "www.googleapis.com"
    assert parse_qs(url.query) == {"mimeType": ["text/plain"]}
    assert all(kw == dict(timeout=30, allow_redirects=False) for _, kw in session.calls)


@pytest.mark.parametrize("key,value", [("id", "wrong_id"), ("name", "wrong title"),
    ("mimeType", "text/plain"), ("trashed", True), ("trashed", None),
    ("version", None), ("version", True), ("version", "bad"), ("version", 7)])
def test_invalid_metadata_stops_before_export(key, value):
    reader, session = make_reader(first={**META, key: value})
    with pytest.raises(RuntimeError):
        reader.read_document(SPEC)
    assert len(session.calls) == 1


@pytest.mark.parametrize("key,value", [("version", "8"), ("modifiedTime", "changed"),
                                      ("name", "changed"), ("trashed", True)])
def test_change_during_export_rejected(key, value):
    reader, _ = make_reader(last={**META, key: value})
    with pytest.raises(RuntimeError):
        reader.read_document(SPEC)


@pytest.mark.parametrize("raw", [b"", b"\xff", b"x" * (MAX_DOCUMENT_BYTES + 1), "not bytes"])
def test_invalid_content_rejected(raw):
    reader, session = make_reader(raw=raw)
    with pytest.raises(RuntimeError):
        reader.read_document(SPEC)
    assert len(session.calls) == 2


@pytest.mark.parametrize("status,error", [(401, PermissionError), (403, PermissionError),
    (500, ConnectionError), (502, ConnectionError), (503, ConnectionError),
    (504, ConnectionError), (302, RuntimeError), (400, RuntimeError), (429, RuntimeError)])
def test_http_failures_are_typed_and_do_not_retry_here(status, error):
    session = Session([Response(status=status)])
    reader = GoogleDriveSwimSourceReader(session)
    with pytest.raises(error):
        reader.read_document(SPEC)
    assert len(session.calls) == 1


@pytest.mark.parametrize("error", [TimeoutError("private details"), ConnectionError("private details")])
def test_transport_exception_sanitized(error):
    reader = GoogleDriveSwimSourceReader(Session([error]))
    with pytest.raises(ConnectionError, match="^SWIM_DRIVE_TRANSPORT_UNAVAILABLE$"):
        reader.read_document(SPEC)


@pytest.mark.parametrize("change", [dict(document_id="../wrong"), dict(expected_title=" "),
                                    dict(role="wrong"), dict(document_id=None)])
def test_invalid_selector_has_no_network_call(change):
    reader, session = make_reader()
    spec = SimpleNamespace(**{**vars(SPEC), **change})
    with pytest.raises(ValueError):
        reader.read_document(spec)
    assert session.calls == []


def test_naive_clock_rejected():
    reader, _ = make_reader()
    reader._now_fn = lambda: datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="CLOCK_INVALID"):
        reader.read_document(SPEC)


def test_markdown_is_not_unescaped_or_repaired():
    raw = b'\\[SWIM\\_AUDIT\\_BEGIN:test\\_v1\\]\n{"a\\_b":1}\n'
    reader, _ = make_reader(raw=raw)
    entry, text = reader.read_document(SPEC)
    assert text.encode() == raw
    assert entry["content_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "[SWIM_AUDIT_BEGIN:test_v1]" not in text


def test_feeds_existing_acquisition_source_contract_and_parser():
    import asyncio
    import json
    from scripts.ironman_jobs.swim_audit_acquisition import (
        DocumentSpec, RECORD_SCHEMA, _source, extract_record,
    )
    from scripts.ironman_jobs.swim_audit_report import payload_sha256
    record = {"schema": RECORD_SCHEMA, "target": {"synthetic": "target"},
              "recovery": {"source_ref": SPEC.document_id}}
    raw = ("[SWIM_AUDIT_BEGIN:test_v1]\n" + json.dumps(record)
           + "\n[SWIM_AUDIT_END:test_v1]\n").encode()
    reader, _ = make_reader(raw=raw)
    spec = DocumentSpec(SPEC.role, SPEC.document_id, SPEC.expected_title)
    entry, text = asyncio.run(_source(reader, spec, lambda: NOW))
    actual = extract_record(text, "test_v1")
    assert actual == record
    assert payload_sha256(actual) == payload_sha256(record)
    assert entry["content_sha256"] == hashlib.sha256(raw).hexdigest()
