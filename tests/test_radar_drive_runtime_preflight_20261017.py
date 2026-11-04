import json
from pathlib import Path

from scripts.ironman_jobs.radar_drive_runtime_preflight_20261017 import preflight


def _roster(path: Path):
    path.write_text(json.dumps({
        "athletes": [
            {"athlete_id": 2932097, "name": "A", "enabled": True},
            {"athlete_id": 4480273, "name": "B", "enabled": True},
        ]
    }))


def _sources(path: Path):
    def source(name):
        return {"document_id": "id-" + name, "expected_title": "title-" + name}
    path.write_text(json.dumps({
        "schema": "IRONMAN_RADAR_CONTEXT_SOURCES_V1",
        "global_documents": {
            "core_index": source("core"),
            "master_coaching_context": source("master"),
            "decision_log": source("decision"),
            "open_questions_roadmap": source("open"),
            "workstream_state": source("state"),
        },
        "specialist_documents": [source("protocol")],
        "athletes": {
            "2932097": {"athlete_card": source("a")},
            "4480273": {"athlete_card": source("b")},
        },
    }))
    path.chmod(0o600)


def _credentials(path: Path):
    path.write_text(json.dumps({
        "type": "service_account",
        "client_email": "reader@example.invalid",
        "private_key": "not-a-real-key",
    }))
    path.chmod(0o600)


def test_preflight_reports_missing_without_writes(tmp_path, monkeypatch):
    roster = tmp_path / "roster.json"
    _roster(roster)
    outcome = preflight(tmp_path / "missing-creds.json", tmp_path / "missing-sources.json", roster)
    assert outcome["credentials"] == "MISSING"
    assert outcome["sources"] == "MISSING"
    assert outcome["ready_for_live_canary"] is False
    assert outcome["drive_writes"] == 0
    assert outcome["trainingpeaks_writes"] == 0
    assert outcome["ai_calls"] == 0


def test_preflight_validates_secure_source_roster_and_credentials(tmp_path):
    roster = tmp_path / "roster.json"
    sources = tmp_path / "sources.json"
    creds = tmp_path / "creds.json"
    _roster(roster)
    _sources(sources)
    _credentials(creds)
    outcome = preflight(creds, sources, roster)
    assert outcome["credentials"] == "READY"
    assert outcome["sources"] == "READY"
    assert outcome["source_roster_count"] == 2
    assert outcome["specialist_document_count"] == 1


def test_preflight_rejects_open_permissions(tmp_path):
    roster = tmp_path / "roster.json"
    sources = tmp_path / "sources.json"
    creds = tmp_path / "creds.json"
    _roster(roster)
    _sources(sources)
    _credentials(creds)
    sources.chmod(0o644)
    creds.chmod(0o644)
    outcome = preflight(creds, sources, roster)
    assert outcome["credentials"].startswith("PERMISSIONS_TOO_OPEN")
    assert outcome["sources"].startswith("PERMISSIONS_TOO_OPEN")
    assert outcome["ready_for_live_canary"] is False
