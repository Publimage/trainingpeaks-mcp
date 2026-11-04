from scripts.ironman_jobs.coaching_radar_context_sources_v0 import (
    context_specs_for_athlete,
    load_private_source_config,
)


def _source(role):
    return {"document_id": "id-" + role, "expected_title": "title-" + role}


def _source_config():
    return {
        "schema": "IRONMAN_RADAR_CONTEXT_SOURCES_V1",
        "global_documents": {
            "core_index": _source("core"),
            "master_coaching_context": _source("master"),
            "decision_log": _source("decision"),
            "open_questions_roadmap": _source("open"),
            "workstream_state": _source("state"),
        },
        "specialist_documents": [_source("protocol"), _source("coaching-state")],
        "athletes": {
            "2932097": {"athlete_card": _source("polverari")},
            "4480273": {"athlete_card": _source("moglioni")},
        },
    }


def test_private_source_config_requires_exact_active_roster(tmp_path):
    import json
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(_source_config()))
    path.chmod(0o600)
    loaded = load_private_source_config(path, active_athlete_ids={2932097, 4480273})
    documents, specialist = context_specs_for_athlete(loaded, athlete_id=2932097)
    assert set(documents) == {
        "core_index", "master_coaching_context", "decision_log",
        "open_questions_roadmap", "athlete_card", "workstream_state",
    }
    assert documents["athlete_card"].document_id == "id-polverari"
    assert len(specialist) == 2


def test_private_source_config_fails_on_roster_drift(tmp_path):
    import json
    import pytest
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(_source_config()))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="KB_SOURCE_ROSTER_MISMATCH"):
        load_private_source_config(path, active_athlete_ids={2932097})


def test_private_source_config_fails_if_permissions_are_open(tmp_path):
    import json
    import pytest
    path = tmp_path / "sources.json"
    path.write_text(json.dumps(_source_config()))
    path.chmod(0o644)
    with pytest.raises(RuntimeError, match="KB_SOURCE_CONFIG_PERMISSIONS_TOO_OPEN"):
        load_private_source_config(path, active_athlete_ids={2932097, 4480273})
