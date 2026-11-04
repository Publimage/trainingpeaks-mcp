"""Reconcile a pseudonymous provider review with the private Radar benchmark case.

Runs locally after a provider call. The provider sees only case_ref; athlete
identity and hidden benchmark expectations stay server-side.
"""
from __future__ import annotations

import hashlib
from typing import Any

PROVIDER_SCHEMA = "IRONMAN_RADAR_AI_PROVIDER_REVIEW_V1"
INTERNAL_SCHEMA = "IRONMAN_COACHING_RADAR_AI_REVIEW_V1"


def private_case_ref(private_case: dict[str, Any]) -> str:
    evidence = str((private_case.get("radar") or {}).get("evidence_sha256") or "")
    as_of = str(private_case.get("as_of") or "")
    if len(evidence) != 64 or not as_of:
        raise ValueError("PROVIDER_REVIEW_PRIVATE_CASE_BINDING_INVALID")
    return "radar-" + hashlib.sha256(f"{evidence}:{as_of}".encode("utf-8")).hexdigest()[:16]


def reconcile_provider_review(
    provider_review: dict[str, Any],
    *,
    private_case: dict[str, Any],
) -> dict[str, Any]:
    if provider_review.get("schema") != PROVIDER_SCHEMA:
        raise ValueError("PROVIDER_REVIEW_SCHEMA_MISMATCH")
    if provider_review.get("mode") != "SHADOW_READ_ONLY":
        raise ValueError("PROVIDER_REVIEW_MODE_MISMATCH")
    expected_ref = private_case_ref(private_case)
    if provider_review.get("case_ref") != expected_ref:
        raise ValueError("PROVIDER_REVIEW_CASE_REF_MISMATCH")
    if str(provider_review.get("as_of") or "") != str(private_case.get("as_of") or ""):
        raise ValueError("PROVIDER_REVIEW_AS_OF_MISMATCH")

    if provider_review.get("trainingpeaks_writes") != 0:
        raise ValueError("PROVIDER_REVIEW_TP_WRITE_CLAIM")
    if provider_review.get("drive_writes") != 0:
        raise ValueError("PROVIDER_REVIEW_DRIVE_WRITE_CLAIM")
    if provider_review.get("workout_mutations") is not False:
        raise ValueError("PROVIDER_REVIEW_WORKOUT_MUTATION_CLAIM")
    if provider_review.get("published") is not False:
        raise ValueError("PROVIDER_REVIEW_PUBLISH_CLAIM")

    observations = provider_review.get("observations")
    if not isinstance(observations, list):
        raise ValueError("PROVIDER_REVIEW_OBSERVATIONS_INVALID")
    for item in observations:
        if not isinstance(item, dict):
            raise ValueError("PROVIDER_REVIEW_OBSERVATION_INVALID")
        if not str(item.get("observation") or "").strip():
            raise ValueError("PROVIDER_REVIEW_OBSERVATION_TEXT_MISSING")
        if not isinstance(item.get("evidence_refs"), list):
            raise ValueError("PROVIDER_REVIEW_EVIDENCE_REFS_INVALID")
        if not str(item.get("uncertainty") or "").strip():
            raise ValueError("PROVIDER_REVIEW_UNCERTAINTY_MISSING")

    radar = private_case.get("radar") or {}
    selective = private_case.get("selective_context") or {}
    internal = {
        "schema": INTERNAL_SCHEMA,
        "mode": "SHADOW_READ_ONLY",
        "athlete_id": int(private_case["athlete_id"]),
        "as_of": private_case["as_of"],
        "input_fingerprint_sha256": private_case["input_fingerprint_sha256"],
        "radar_evidence_sha256": radar["evidence_sha256"],
        "context_fingerprint_sha256": selective["context_fingerprint_sha256"],
        "attention": provider_review.get("attention"),
        "behavior_codes": list(provider_review.get("behavior_codes") or []),
        "observations": observations,
        "questions_for_coach": list(provider_review.get("questions_for_coach") or []),
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "workout_mutations": False,
        "published": False,
        "provider_case_ref": expected_ref,
    }
    return internal
