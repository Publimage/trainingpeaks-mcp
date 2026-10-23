import copy

import pytest

from scripts.ironman_jobs.coaching_radar_ai_context_contract_v0 import (
    INPUT_SCHEMA,
    MODE,
    OUTPUT_SCHEMA,
    build_ai_context_input,
    validate_ai_review_output,
)


def _radar():
    return {
        "schema": "IRONMAN_COACHING_RADAR_V1",
        "mode": "READ_ONLY",
        "athlete_id": 2932097,
        "athlete_name": "Massimiliano Polverari",
        "as_of": "2026-10-17",
        "status": "YELLOW",
        "review_required": True,
        "alerts": [{"category": "DURATION_SHORT", "workout_id": "1"}],
        "upcoming": [],
        "data_quality": {"wellness_metrics_count": 0},
        "source": {"workout_count": 4},
        "evidence_sha256": "a" * 64,
        "trainingpeaks_writes": 0,
    }


def _entry(title):
    return {
        "title": title,
        "document_id": "id-" + title,
        "source_version": "123",
        "content_sha256": "b" * 64,
    }


def _kb():
    roles = [
        "core_index",
        "master_coaching_context",
        "decision_log",
        "open_questions_roadmap",
        "athlete_card",
        "workstream_state",
    ]
    return {
        "validation": {
            "ai_context_gate": "PASS",
            "athlete_id": 2932097,
            "context_fingerprint_sha256": "c" * 64,
        },
        "manifest": {
            "source_of_truth": "IRONMAN — KNOWLEDGE BASE",
            "generated_at_utc": "2026-10-17T10:00:00+00:00",
            "documents": {role: _entry(role) for role in roles},
            "specialist_documents": [_entry("13_ATHLETE_COACHING_PROTOCOL")],
        },
        "contents": {
            **{role: "content " + role for role in roles},
            "specialist:0": "specialist content",
        },
    }


def _review(packet):
    return {
        "schema": OUTPUT_SCHEMA,
        "mode": MODE,
        "athlete_id": packet["athlete_id"],
        "as_of": packet["as_of"],
        "input_fingerprint_sha256": packet["input_fingerprint_sha256"],
        "radar_evidence_sha256": packet["radar"]["evidence_sha256"],
        "context_fingerprint_sha256": packet["knowledge_base"]["context_fingerprint_sha256"],
        "attention": "COACH_REVIEW",
        "observations": [{
            "observation": "La durata e' inferiore al pianificato; serve interpretazione contestuale.",
            "evidence_refs": ["radar.alerts[0]", "knowledge_base.athlete_card"],
            "uncertainty": "Non e' noto dal solo dato se la seduta sia stata interrotta volontariamente.",
        }],
        "questions_for_coach": ["Verificare il motivo della durata ridotta."],
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "workout_mutations": False,
        "published": False,
    }


def test_build_packet_is_shadow_read_only_and_fingerprinted():
    packet = build_ai_context_input(_radar(), _kb())
    assert packet["schema"] == INPUT_SCHEMA
    assert packet["mode"] == MODE
    assert packet["guardrails"]["coach_is_final_decision_maker"] is True
    assert packet["guardrails"]["workout_mutations_allowed"] is False
    assert packet["trainingpeaks_writes"] == 0
    assert packet["drive_writes"] == 0
    assert packet["ai_calls"] == 0
    assert len(packet["input_fingerprint_sha256"]) == 64


def test_rejects_kb_gate_not_passed():
    kb = _kb()
    kb["validation"]["ai_context_gate"] = "FAIL"
    with pytest.raises(ValueError, match="AI_KB_CONTEXT_GATE_NOT_PASS"):
        build_ai_context_input(_radar(), kb)


def test_rejects_athlete_mismatch():
    kb = _kb()
    kb["validation"]["athlete_id"] = 4480273
    with pytest.raises(ValueError, match="AI_KB_ATHLETE_MISMATCH"):
        build_ai_context_input(_radar(), kb)


def test_rejects_trainingpeaks_write_input():
    radar = _radar()
    radar["trainingpeaks_writes"] = 1
    with pytest.raises(ValueError, match="AI_RADAR_WRITE_GUARD_FAILED"):
        build_ai_context_input(radar, _kb())


def test_valid_review_requires_coach_decision_and_keeps_zero_writes():
    packet = build_ai_context_input(_radar(), _kb())
    result = validate_ai_review_output(_review(packet), input_packet=packet)
    assert result["attention"] == "COACH_REVIEW"
    assert result["coach_decision_required"] is True
    assert result["trainingpeaks_writes"] == 0
    assert result["drive_writes"] == 0


def test_review_must_match_exact_input_fingerprint():
    packet = build_ai_context_input(_radar(), _kb())
    review = _review(packet)
    review["input_fingerprint_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="AI_REVIEW_INPUT_FINGERPRINT_MISMATCH"):
        validate_ai_review_output(review, input_packet=packet)


def test_review_observation_requires_evidence_refs_and_uncertainty():
    packet = build_ai_context_input(_radar(), _kb())
    review = _review(packet)
    review["observations"][0]["evidence_refs"] = []
    with pytest.raises(ValueError, match="AI_REVIEW_EVIDENCE_REFS_MISSING"):
        validate_ai_review_output(review, input_packet=packet)


def test_review_cannot_claim_side_effects():
    packet = build_ai_context_input(_radar(), _kb())
    review = _review(packet)
    review["workout_mutations"] = True
    with pytest.raises(ValueError, match="AI_REVIEW_PROHIBITED_SIDE_EFFECT:workout_mutations"):
        validate_ai_review_output(review, input_packet=packet)


def test_packet_fingerprint_changes_if_radar_changes():
    first = build_ai_context_input(_radar(), _kb())
    radar = copy.deepcopy(_radar())
    radar["alerts"][0]["workout_id"] = "2"
    second = build_ai_context_input(radar, _kb())
    assert first["input_fingerprint_sha256"] != second["input_fingerprint_sha256"]
