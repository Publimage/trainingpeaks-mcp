"""Contract layer for future Coaching Radar AI interpretation.

This module performs no AI/network/provider calls. It creates and validates a
shadow-mode review packet from an already verified TrainingPeaks Radar report
and an already verified canonical Knowledge Base bundle.

The contract intentionally keeps the AI advisory:
- no TrainingPeaks writes
- no Drive writes
- no workout mutations
- no publishing
- coach remains the decision maker
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

INPUT_SCHEMA = "IRONMAN_COACHING_RADAR_AI_INPUT_V1"
OUTPUT_SCHEMA = "IRONMAN_COACHING_RADAR_AI_REVIEW_V1"
MODE = "SHADOW_READ_ONLY"

_ALLOWED_ATTENTION = {"NO_REVIEW", "COACH_REVIEW", "PRIORITY_REVIEW"}


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_ai_context_input(
    radar_report: dict[str, Any],
    kb_bundle: dict[str, Any],
) -> dict[str, Any]:
    """Build a private in-memory input packet for a future AI provider."""
    if radar_report.get("schema") != "IRONMAN_COACHING_RADAR_V1":
        raise ValueError("AI_RADAR_SCHEMA_MISMATCH")
    if radar_report.get("mode") != "READ_ONLY":
        raise ValueError("AI_RADAR_MODE_NOT_READ_ONLY")
    if radar_report.get("trainingpeaks_writes") != 0:
        raise ValueError("AI_RADAR_WRITE_GUARD_FAILED")

    athlete_id = int(radar_report.get("athlete_id") or 0)
    if athlete_id <= 0:
        raise ValueError("AI_RADAR_ATHLETE_ID_INVALID")
    as_of = str(radar_report.get("as_of") or "").strip()
    if not as_of:
        raise ValueError("AI_RADAR_AS_OF_MISSING")
    evidence_sha = str(radar_report.get("evidence_sha256") or "").strip()
    if len(evidence_sha) != 64:
        raise ValueError("AI_RADAR_EVIDENCE_SHA_INVALID")

    validation = kb_bundle.get("validation")
    manifest = kb_bundle.get("manifest")
    contents = kb_bundle.get("contents")
    if not isinstance(validation, dict) or validation.get("ai_context_gate") != "PASS":
        raise ValueError("AI_KB_CONTEXT_GATE_NOT_PASS")
    if int(validation.get("athlete_id") or 0) != athlete_id:
        raise ValueError("AI_KB_ATHLETE_MISMATCH")
    if not isinstance(manifest, dict) or not isinstance(contents, dict):
        raise ValueError("AI_KB_BUNDLE_INCOMPLETE")

    context_fingerprint = str(validation.get("context_fingerprint_sha256") or "")
    if len(context_fingerprint) != 64:
        raise ValueError("AI_KB_CONTEXT_FINGERPRINT_INVALID")

    required_content_roles = {
        "core_index",
        "master_coaching_context",
        "decision_log",
        "open_questions_roadmap",
        "athlete_card",
        "workstream_state",
    }
    if not required_content_roles.issubset(contents):
        missing = sorted(required_content_roles - set(contents))
        raise ValueError("AI_KB_CONTENT_ROLE_MISSING:" + ",".join(missing))
    if not any(key.startswith("specialist:") for key in contents):
        raise ValueError("AI_KB_SPECIALIST_CONTENT_MISSING")
    if any(not isinstance(value, str) or not value.strip() for value in contents.values()):
        raise ValueError("AI_KB_EMPTY_CONTENT")

    source_index = {
        role: {
            "title": item["title"],
            "document_id": item["document_id"],
            "source_version": item["source_version"],
            "content_sha256": item["content_sha256"],
        }
        for role, item in manifest["documents"].items()
    }
    source_index["specialist_documents"] = [
        {
            "title": item["title"],
            "document_id": item["document_id"],
            "source_version": item["source_version"],
            "content_sha256": item["content_sha256"],
        }
        for item in manifest["specialist_documents"]
    ]

    packet = {
        "schema": INPUT_SCHEMA,
        "mode": MODE,
        "athlete_id": athlete_id,
        "athlete_name": radar_report.get("athlete_name"),
        "as_of": as_of,
        "radar": {
            "status": radar_report.get("status"),
            "review_required": bool(radar_report.get("review_required")),
            "alerts": radar_report.get("alerts") or [],
            "upcoming": radar_report.get("upcoming") or [],
            "data_quality": radar_report.get("data_quality") or {},
            "source": radar_report.get("source") or {},
            "evidence_sha256": evidence_sha,
        },
        "knowledge_base": {
            "source_of_truth": manifest.get("source_of_truth"),
            "generated_at_utc": manifest.get("generated_at_utc"),
            "context_fingerprint_sha256": context_fingerprint,
            "source_index": source_index,
            "contents": contents,
        },
        "guardrails": {
            "purpose": "contextual_analysis_for_coach_review",
            "coach_is_final_decision_maker": True,
            "trainingpeaks_writes_allowed": False,
            "drive_writes_allowed": False,
            "workout_mutations_allowed": False,
            "publishing_allowed": False,
            "must_cite_evidence": True,
            "must_surface_uncertainty": True,
            "absence_of_data_is_not_positive_evidence": True,
        },
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
    }
    packet["input_fingerprint_sha256"] = _sha256(packet)
    return packet


def validate_ai_review_output(
    review: dict[str, Any],
    *,
    input_packet: dict[str, Any],
) -> dict[str, Any]:
    """Fail closed on a future model response before it can reach coach-facing UI."""
    if review.get("schema") != OUTPUT_SCHEMA:
        raise ValueError("AI_REVIEW_SCHEMA_MISMATCH")
    if review.get("mode") != MODE:
        raise ValueError("AI_REVIEW_MODE_MISMATCH")
    if int(review.get("athlete_id") or 0) != int(input_packet["athlete_id"]):
        raise ValueError("AI_REVIEW_ATHLETE_MISMATCH")
    if str(review.get("as_of") or "") != str(input_packet["as_of"]):
        raise ValueError("AI_REVIEW_AS_OF_MISMATCH")
    if review.get("input_fingerprint_sha256") != input_packet.get("input_fingerprint_sha256"):
        raise ValueError("AI_REVIEW_INPUT_FINGERPRINT_MISMATCH")
    if review.get("radar_evidence_sha256") != input_packet["radar"]["evidence_sha256"]:
        raise ValueError("AI_REVIEW_RADAR_EVIDENCE_MISMATCH")
    if review.get("context_fingerprint_sha256") != input_packet["knowledge_base"]["context_fingerprint_sha256"]:
        raise ValueError("AI_REVIEW_CONTEXT_FINGERPRINT_MISMATCH")

    attention = review.get("attention")
    if attention not in _ALLOWED_ATTENTION:
        raise ValueError("AI_REVIEW_ATTENTION_INVALID")

    observations = review.get("observations")
    if not isinstance(observations, list):
        raise ValueError("AI_REVIEW_OBSERVATIONS_INVALID")
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError("AI_REVIEW_OBSERVATION_INVALID")
        if not str(item.get("observation") or "").strip():
            raise ValueError("AI_REVIEW_OBSERVATION_TEXT_MISSING")
        refs = item.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            raise ValueError("AI_REVIEW_EVIDENCE_REFS_MISSING")
        if not str(item.get("uncertainty") or "").strip():
            raise ValueError("AI_REVIEW_UNCERTAINTY_MISSING")

    questions = review.get("questions_for_coach")
    if not isinstance(questions, list):
        raise ValueError("AI_REVIEW_COACH_QUESTIONS_INVALID")

    prohibited = (
        "trainingpeaks_writes",
        "drive_writes",
        "workout_mutations",
        "published",
    )
    for field in prohibited:
        if review.get(field) not in (0, False, None):
            raise ValueError(f"AI_REVIEW_PROHIBITED_SIDE_EFFECT:{field}")

    return {
        "schema": OUTPUT_SCHEMA,
        "mode": MODE,
        "athlete_id": input_packet["athlete_id"],
        "as_of": input_packet["as_of"],
        "attention": attention,
        "observation_count": len(observations),
        "question_count": len(questions),
        "input_fingerprint_sha256": input_packet["input_fingerprint_sha256"],
        "review_fingerprint_sha256": _sha256(review),
        "coach_decision_required": True,
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
    }
