from pathlib import Path
from datetime import datetime, timezone

import pytest

from scripts.ironman_jobs.coaching_radar_drive_context_adapter_v0 import (
    ContextDocumentSpec,
    DRIVE_READONLY_SCOPE,
    GoogleDriveContextReader,
    build_context_bundle,
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


class BundleReader:
    def read_document(self, spec):
        marker = "b" if spec.role.startswith("specialist") else "a"
        return ({
            "title": spec.expected_title,
            "document_id": spec.document_id,
            "source_version": "99",
            "version_kind": "DRIVE_FILE_VERSION",
            "modified_time": NOW.isoformat(),
            "retrieved_at_utc": NOW.isoformat(),
            "content_sha256": marker * 64,
            "source": "GOOGLE_DRIVE",
        }, f"# {spec.expected_title}\n")


def _bundle_specs():
    roles = (
        "core_index",
        "master_coaching_context",
        "decision_log",
        "open_questions_roadmap",
        "athlete_card",
        "workstream_state",
    )
    return {
        role: ContextDocumentSpec(role, "doc-" + role, role)
        for role in roles
    }


def test_bundle_requires_all_canonical_roles_and_specialist_and_passes_gate():
    bundle = build_context_bundle(
        BundleReader(),
        athlete_id=2932097,
        documents=_bundle_specs(),
        specialist_documents=[
            ContextDocumentSpec("specialist_training", "doc-specialist", "specialist")
        ],
        now_utc=NOW,
    )
    assert bundle["validation"]["ai_context_gate"] == "PASS"
    assert bundle["validation"]["document_count"] == 7
    assert set(bundle["contents"]) == set(_bundle_specs()) | {"specialist:0"}


def test_bundle_missing_role_fails_before_reading():
    specs = _bundle_specs()
    del specs["athlete_card"]
    with pytest.raises(ValueError, match="KB_CONTEXT_SPEC_ROLE_MISSING:athlete_card"):
        build_context_bundle(
            BundleReader(),
            athlete_id=2932097,
            documents=specs,
            specialist_documents=[
                ContextDocumentSpec("specialist_training", "doc-specialist", "specialist")
            ],
            now_utc=NOW,
        )


def test_live_canary_contract_is_metadata_only():
    canary = Path("scripts/ironman_jobs/coaching_radar_drive_live_canary_20261017.py").read_text()
    assert "DRIVE_READONLY_SCOPE" in canary
    assert '"drive_writes": 0' in canary
    assert '"trainingpeaks_writes": 0' in canary
    assert "print(content)" not in canary
    assert "KB_CREDENTIALS_FILE_PERMISSIONS_TOO_OPEN" in canary


def test_drive_runtime_prepare_is_isolated_and_non_disruptive():
    installer = Path("scripts/ironman_jobs/prepare_radar_drive_reader_runtime_20261017.sh").read_text()
    assert "/opt/ironman-prefect/drive-reader" in installer
    assert "google-auth[requests]==2.62.0" in installer
    assert "RADAR_DRIVE_READER_RUNTIME_PASS" in installer
    assert "systemctl restart" not in installer
    assert "reboot" not in installer
    assert "git config --global safe.directory" not in installer


def test_private_source_routing_requires_exact_roster(tmp_path):
    import json
    from scripts.ironman_jobs.coaching_radar_context_sources_v0 import (
        context_specs_for_athlete,
        load_private_source_config,
    )

    def source(role):
        return {"document_id": "id-" + role, "expected_title": "title-" + role}

    raw = {
        "schema": "IRONMAN_RADAR_CONTEXT_SOURCES_V1",
        "global_documents": {
            "core_index": source("core"),
            "master_coaching_context": source("master"),
            "decision_log": source("decision"),
            "open_questions_roadmap": source("open"),
            "workstream_state": source("state"),
        },
        "specialist_documents": [source("protocol"), source("coaching-state")],
        "athletes": {
            "2932097": {"athlete_card": source("polverari")},
            "4480273": {"athlete_card": source("moglioni")},
        },
    }
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(raw))
    path.chmod(0o600)
    loaded = load_private_source_config(path, active_athlete_ids={2932097, 4480273})
    documents, specialist = context_specs_for_athlete(loaded, athlete_id=2932097)
    assert set(documents) == {
        "core_index", "master_coaching_context", "decision_log",
        "open_questions_roadmap", "athlete_card", "workstream_state",
    }
    assert len(specialist) == 2

    with pytest.raises(ValueError, match="KB_SOURCE_ROSTER_MISMATCH"):
        load_private_source_config(path, active_athlete_ids={2932097})

    path.chmod(0o644)
    with pytest.raises(RuntimeError, match="KB_SOURCE_CONFIG_PERMISSIONS_TOO_OPEN"):
        load_private_source_config(path, active_athlete_ids={2932097, 4480273})


def test_bundle_fails_if_athlete_card_provider_id_is_wrong():
    class WrongCardReader(BundleReader):
        def read_document(self, spec):
            entry, content = super().read_document(spec)
            if spec.role == "athlete_card":
                content = "# athlete\\nTrainingPeaks ID: 9999999\\n"
            return entry, content

    with pytest.raises(ValueError, match="KB_ATHLETE_CARD_PROVIDER_ID_MISMATCH"):
        build_context_bundle(
            WrongCardReader(),
            athlete_id=2932097,
            documents=_bundle_specs(),
            specialist_documents=[
                ContextDocumentSpec("specialist_training", "doc-specialist", "specialist")
            ],
            now_utc=NOW,
        )
