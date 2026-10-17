import pytest

from scripts.ironman_jobs.reconcile_coaching_radar_ai_provider_review_v1 import (
    private_case_ref,
    reconcile_provider_review,
)


def _case():
    return {
        "schema": "IRONMAN_RADAR_AI_PRIVATE_BENCHMARK_CASE_V1",
        "athlete_id": 2932097,
        "athlete_name": "Massimiliano Polverari",
        "as_of": "2026-10-17",
        "input_fingerprint_sha256": "a" * 64,
        "radar": {"evidence_sha256": "b" * 64},
        "selective_context": {"context_fingerprint_sha256": "c" * 64},
        "benchmark_expectations": {
            "required_behavior_codes": ["CITE_EVIDENCE"],
            "forbidden_behavior_codes": [],
        },
    }


def _review(case):
    return {
        "schema": "IRONMAN_RADAR_AI_PROVIDER_REVIEW_V1",
        "mode": "SHADOW_READ_ONLY",
        "case_ref": private_case_ref(case),
        "as_of": case["as_of"],
        "attention": "COACH_REVIEW",
        "behavior_codes": ["CITE_EVIDENCE", "COACH_DECISION_REQUIRED"],
        "observations": [{
            "observation": "Controllare il segnale.",
            "evidence_refs": ["radar.alerts[0]"],
            "uncertainty": "La causa non e' dimostrata.",
        }],
        "questions_for_coach": [],
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "workout_mutations": False,
        "published": False,
    }


def test_reconciliation_restores_identity_only_server_side():
    case = _case()
    review = _review(case)
    assert "2932097" not in str(review)
    internal = reconcile_provider_review(review, private_case=case)
    assert internal["athlete_id"] == 2932097
    assert internal["provider_case_ref"] == review["case_ref"]
    assert internal["radar_evidence_sha256"] == "b" * 64
    assert internal["context_fingerprint_sha256"] == "c" * 64
    assert internal["trainingpeaks_writes"] == 0


def test_reconciliation_rejects_wrong_case_ref():
    case = _case()
    review = _review(case)
    review["case_ref"] = "radar-wrong"
    with pytest.raises(ValueError, match="PROVIDER_REVIEW_CASE_REF_MISMATCH"):
        reconcile_provider_review(review, private_case=case)


def test_reconciliation_rejects_side_effect_claim():
    case = _case()
    review = _review(case)
    review["trainingpeaks_writes"] = 1
    with pytest.raises(ValueError, match="PROVIDER_REVIEW_TP_WRITE_CLAIM"):
        reconcile_provider_review(review, private_case=case)


def test_reconciliation_requires_uncertainty():
    case = _case()
    review = _review(case)
    review["observations"][0]["uncertainty"] = ""
    with pytest.raises(ValueError, match="PROVIDER_REVIEW_UNCERTAINTY_MISSING"):
        reconcile_provider_review(review, private_case=case)
