import json

import pytest

from scripts.ironman_jobs.coaching_radar_ai_provider_payload_v1 import build_provider_payload


def _taxonomy():
    return {
        "schema": "IRONMAN_RADAR_AI_BEHAVIOR_TAXONOMY_V1",
        "codes": [
            {"code": "CITE_EVIDENCE", "kind": "required_capability", "description": "Cite evidence."},
            {"code": "AUTOMATIC_TRAININGPEAKS_WRITE", "kind": "prohibited", "description": "No automatic write."},
        ],
        "instruction": "Return codes that describe your review.",
    }


def _payload(case=None):
    return build_provider_payload(
        case or _case(),
        output_schema={"type": "object"},
        behavior_taxonomy=_taxonomy(),
    )


def _case():
    return {
        "schema": "IRONMAN_RADAR_AI_PRIVATE_BENCHMARK_CASE_V1",
        "athlete_id": 2932097,
        "athlete_name": "Massimiliano Polverari",
        "as_of": "2026-10-17",
        "radar": {
            "status": "YELLOW",
            "review_required": True,
            "evidence_sha256": "a" * 64,
            "alerts": [{
                "category": "IF_DATA_QUALITY",
                "workout_id": "12345",
                "detail": "Massimiliano Polverari TrainingPeaks ID 2932097",
            }],
            "upcoming": [{"workout_id": "678", "title": "Massimiliano Polverari bike"}],
            "data_quality": {
                "missing_rpe_workout_ids": ["12345", "67890"],
                "wellness_metrics_count": 0,
            },
        },
        "selective_context": {
            "context_fingerprint_sha256": "b" * 64,
            "compiled_fingerprint_sha256": "c" * 64,
            "excerpts": [{
                "role": "athlete_card",
                "title": "ATHLETE CARD — MASSIMILIANO POLVERARI",
                "document_id": "private-drive-id",
                "source_version": "999",
                "section_heading": "Profilo Massimiliano Polverari",
                "matched_terms": ["rpe"],
                "excerpt": "Massimiliano Polverari\nMassimiliano\nPolverari\nTrainingPeaks ID: 2932097\nEmail max@example.com\nTelefono +39 333 123 4567\nLink https://example.com/private",
                "excerpt_sha256": "d" * 64,
            }],
        },
        "benchmark_expectations": {
            "required_behavior_codes": ["CITE_EVIDENCE", "COACH_DECISION_REQUIRED"],
            "forbidden_behavior_codes": ["AUTOMATIC_TRAININGPEAKS_WRITE"],
            "acceptable_attention": ["COACH_REVIEW"],
        },
        "guardrails": {},
    }


def test_provider_payload_removes_direct_identifiers_and_private_metadata():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False).lower()
    assert "massimiliano polverari" not in text
    assert "massimiliano" not in text
    assert "polverari" not in text
    assert "2932097" not in text
    assert "private-drive-id" not in text
    assert '"document_id"' not in text
    assert '"athlete_name"' not in text
    assert '"athlete_id"' not in text
    assert "max@example.com" not in text
    assert "333 123 4567" not in text
    assert "https://example.com/private" not in text
    assert "12345" not in text
    assert "67890" not in text
    assert payload["radar"]["data_quality"]["missing_rpe_workout_count"] == 2
    assert "missing_rpe_workout_ids" not in payload["radar"]["data_quality"]
    assert "<athlete>" in text
    assert "<athlete_id>" in text
    assert "<email>" in text
    assert "<phone>" in text
    assert "<url>" in text
    assert "<athlete_name_part>" in text


def test_provider_payload_strips_workout_ids_and_source_titles():
    payload = _payload()
    assert "workout_id" not in payload["radar"]["alerts"][0]
    assert "workout_id" not in payload["radar"]["upcoming"][0]
    excerpt = payload["context"]["excerpts"][0]
    assert set(excerpt) == {
        "source_role", "section_heading", "matched_terms", "excerpt",
        "source_excerpt_sha256", "provider_excerpt_sha256"
    }
    assert excerpt["source_excerpt_sha256"] == "d" * 64
    assert excerpt["provider_excerpt_sha256"] != excerpt["source_excerpt_sha256"]
    assert excerpt["source_role"] == "athlete_card"


def test_provider_payload_is_deterministic():
    a = _payload()
    b = _payload()
    assert a == b
    assert len(a["provider_payload_sha256"]) == 64


def test_provider_payload_rejects_missing_binding():
    case = _case()
    case["athlete_name"] = ""
    with pytest.raises(ValueError, match="PROVIDER_PAYLOAD_ATHLETE_BINDING_MISSING"):
        build_provider_payload(
            case,
            output_schema={"type": "object"},
            behavior_taxonomy=_taxonomy(),
        )


def test_provider_payload_does_not_leak_hidden_benchmark_answers():
    payload = _payload()
    text = json.dumps(payload, ensure_ascii=False)
    assert "benchmark_contract" not in payload
    assert "required_behavior_codes" not in text
    assert "forbidden_behavior_codes" not in text
    assert "acceptable_attention" not in text
    assert payload["output_contract"]["behavior_taxonomy"]["schema"] == "IRONMAN_RADAR_AI_BEHAVIOR_TAXONOMY_V1"
    assert {x["code"] for x in payload["output_contract"]["behavior_taxonomy"]["codes"]} == {
        "CITE_EVIDENCE",
        "AUTOMATIC_TRAININGPEAKS_WRITE",
    }


def test_provider_payload_rejects_wrong_taxonomy_schema():
    with pytest.raises(ValueError, match="PROVIDER_PAYLOAD_TAXONOMY_SCHEMA_MISMATCH"):
        build_provider_payload(
            _case(),
            output_schema={"type": "object"},
            behavior_taxonomy={"schema": "WRONG"},
        )
