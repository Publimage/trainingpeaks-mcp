from datetime import datetime, timezone, timedelta

import pytest

from scripts.ironman_jobs.coaching_radar_kb_context_v0 import (
    REQUIRED_ROLES,
    SOURCE_OF_TRUTH,
    validate_kb_context_manifest,
)


NOW = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)


def _doc(role: str, when: datetime = NOW) -> dict:
    return {
        "title": role,
        "document_id": "doc-" + role,
        "revision_id": "rev-" + role,
        "retrieved_at_utc": when.isoformat(),
        "content_sha256": ("a" if role != "specialist" else "b") * 64,
        "source": "GOOGLE_DRIVE",
    }


def _manifest() -> dict:
    return {
        "schema": "IRONMAN_KB_CONTEXT_MANIFEST_V1",
        "source_of_truth": SOURCE_OF_TRUTH,
        "athlete_id": 2932097,
        "generated_at_utc": NOW.isoformat(),
        "documents": {role: _doc(role) for role in REQUIRED_ROLES},
        "specialist_documents": [_doc("specialist")],
    }


def test_valid_manifest_passes_and_returns_only_metadata():
    result = validate_kb_context_manifest(_manifest(), athlete_id=2932097, now_utc=NOW)
    assert result["ai_context_gate"] == "PASS"
    assert result["document_count"] == 7
    assert result["specialist_document_count"] == 1
    assert len(result["context_fingerprint_sha256"]) == 64
    assert "documents" not in result


def test_missing_critical_role_fails_closed():
    manifest = _manifest()
    del manifest["documents"]["athlete_card"]
    with pytest.raises(ValueError, match="KB_CRITICAL_ROLE_MISSING:athlete_card"):
        validate_kb_context_manifest(manifest, athlete_id=2932097, now_utc=NOW)


def test_missing_specialist_document_fails_closed():
    manifest = _manifest()
    manifest["specialist_documents"] = []
    with pytest.raises(ValueError, match="KB_SPECIALIST_DOCUMENT_MISSING"):
        validate_kb_context_manifest(manifest, athlete_id=2932097, now_utc=NOW)


def test_stale_manifest_fails_closed():
    manifest = _manifest()
    manifest["generated_at_utc"] = (NOW - timedelta(hours=25)).isoformat()
    with pytest.raises(ValueError, match="KB_MANIFEST_STALE"):
        validate_kb_context_manifest(manifest, athlete_id=2932097, now_utc=NOW)


def test_stale_document_fails_closed():
    manifest = _manifest()
    manifest["documents"]["decision_log"]["retrieved_at_utc"] = (NOW - timedelta(hours=25)).isoformat()
    with pytest.raises(ValueError, match="KB_DOCUMENT_STALE"):
        validate_kb_context_manifest(manifest, athlete_id=2932097, now_utc=NOW)


def test_athlete_mismatch_fails_closed():
    with pytest.raises(ValueError, match="KB_MANIFEST_ATHLETE_MISMATCH"):
        validate_kb_context_manifest(_manifest(), athlete_id=4480273, now_utc=NOW)


def test_duplicate_document_id_fails_closed():
    manifest = _manifest()
    manifest["documents"]["workstream_state"]["document_id"] = manifest["documents"]["athlete_card"]["document_id"]
    with pytest.raises(ValueError, match="KB_DUPLICATE_DOCUMENT_ID"):
        validate_kb_context_manifest(manifest, athlete_id=2932097, now_utc=NOW)


def test_invalid_digest_fails_closed():
    manifest = _manifest()
    manifest["documents"]["core_index"]["content_sha256"] = "not-a-sha"
    with pytest.raises(ValueError, match="KB_DOCUMENT_SHA256_INVALID"):
        validate_kb_context_manifest(manifest, athlete_id=2932097, now_utc=NOW)
