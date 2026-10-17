import json
from pathlib import Path

import pytest

from scripts.ironman_jobs.validate_coaching_radar_ai_context_eval_cases_v1 import validate_cases


def _roster(path: Path):
    path.write_text(json.dumps({
        "athletes": [
            {"athlete_id": 1, "name": "A", "enabled": True},
            {"athlete_id": 2, "name": "B", "enabled": True},
        ]
    }))


def _case(athlete_id, categories, data_quality, expected_topics, *, status="YELLOW"):
    return {
        "athlete_id": athlete_id,
        "categories": categories,
        "data_quality": data_quality,
        "expected_topics": expected_topics,
        "radar_evidence_sha256": ("%064x" % athlete_id)[-64:],
        "radar_status": status,
    }


def _cases(path: Path):
    path.write_text(json.dumps({
        "schema": "IRONMAN_RADAR_AI_CONTEXT_EVAL_CASES_V1",
        "cases": [
            _case(1, ["TSS_DATA_QUALITY"], ["WELLNESS_PRESENT"], ["TSS"]),
            _case(2, [], ["MISSING_RPE"], ["feedback"], status="GREEN"),
        ],
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
    }))


def test_eval_case_manifest_passes_complete_roster(tmp_path):
    roster = tmp_path / "roster.json"
    cases = tmp_path / "cases.json"
    _roster(roster)
    _cases(cases)
    out = validate_cases(cases, roster)
    assert out["gate"] == "PASS"
    assert out["case_count"] == 2
    assert out["zero_alert_cases"] == 1
    assert out["category_counts"] == {"TSS_DATA_QUALITY": 1}


def test_eval_case_manifest_fails_missing_athlete(tmp_path):
    roster = tmp_path / "roster.json"
    cases = tmp_path / "cases.json"
    _roster(roster)
    raw = {
        "schema": "IRONMAN_RADAR_AI_CONTEXT_EVAL_CASES_V1",
        "cases": [_case(1, [], ["MISSING_RPE"], ["feedback"])],
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
    }
    cases.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="AI_CONTEXT_EVAL_ROSTER_INCOMPLETE"):
        validate_cases(cases, roster)


def test_eval_case_manifest_rejects_unsupported_category(tmp_path):
    roster = tmp_path / "roster.json"
    cases = tmp_path / "cases.json"
    _roster(roster)
    raw = {
        "schema": "IRONMAN_RADAR_AI_CONTEXT_EVAL_CASES_V1",
        "cases": [
            _case(1, ["UNKNOWN"], ["WELLNESS_PRESENT"], ["x"]),
            _case(2, [], ["MISSING_RPE"], ["feedback"]),
        ],
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
    }
    cases.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="AI_CONTEXT_EVAL_UNSUPPORTED_CATEGORY"):
        validate_cases(cases, roster)


def test_committed_live_snapshot_covers_current_active_roster():
    out = validate_cases(
        Path("data/coaching_radar_ai_context_eval_cases_v1.json"),
        Path("data/coaching_radar_alberto_group_v1.json"),
    )
    assert out["gate"] == "PASS"
    assert out["case_count"] == 10
    assert out["active_roster_count"] == 10
    assert out["zero_alert_cases"] == 1
    assert out["category_counts"] == {
        "COMPLETION_UNCONFIRMED": 6,
        "DURATION_SHORT": 1,
        "IF_DATA_QUALITY": 4,
        "TSS_DATA_QUALITY": 3,
    }


def test_eval_case_manifest_rejects_unsupported_data_quality(tmp_path):
    roster = tmp_path / "roster.json"
    cases = tmp_path / "cases.json"
    _roster(roster)
    raw = {
        "schema": "IRONMAN_RADAR_AI_CONTEXT_EVAL_CASES_V1",
        "cases": [
            _case(1, [], ["UNKNOWN_FLAG"], ["x"]),
            _case(2, [], ["MISSING_RPE"], ["feedback"]),
        ],
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
    }
    cases.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="AI_CONTEXT_EVAL_UNSUPPORTED_DATA_QUALITY"):
        validate_cases(cases, roster)
