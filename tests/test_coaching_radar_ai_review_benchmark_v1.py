import json
from pathlib import Path

from scripts.ironman_jobs.build_coaching_radar_ai_review_benchmark_v1 import build_benchmark
from scripts.ironman_jobs.score_coaching_radar_ai_review_v1 import score_review


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_committed_benchmark_is_exactly_reproducible_from_frozen_cases():
    source = _load_json("data/coaching_radar_ai_context_eval_cases_v1.json")
    committed = _load_json("data/coaching_radar_ai_review_benchmark_v1.json")
    assert build_benchmark(source) == committed
    assert committed["case_count"] == 10
    assert committed["ai_calls"] == 0
    assert committed["trainingpeaks_writes"] == 0
    assert committed["drive_writes"] == 0


def _good_review(case):
    return {
        "schema": "IRONMAN_COACHING_RADAR_AI_REVIEW_V1",
        "mode": "SHADOW_READ_ONLY",
        "athlete_id": case["athlete_id"],
        "as_of": case["as_of"],
        "input_fingerprint_sha256": "a" * 64,
        "radar_evidence_sha256": case["radar_evidence_sha256"],
        "context_fingerprint_sha256": "b" * 64,
        "attention": case["acceptable_attention"][0],
        "behavior_codes": list(case["required_behavior_codes"]),
        "observations": [{
            "observation": "Review grounded in the frozen case.",
            "evidence_refs": ["radar.alerts[0]"],
            "uncertainty": "Causal interpretation remains uncertain.",
        }],
        "questions_for_coach": [],
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "workout_mutations": False,
        "published": False,
    }


def test_good_review_scores_100_and_passes():
    benchmark = _load_json("data/coaching_radar_ai_review_benchmark_v1.json")
    case = benchmark["cases"][0]
    result = score_review(_good_review(case), case, benchmark["scoring"])
    assert result["pass"] is True
    assert result["score"] == 100
    assert result["hard_fail_reasons"] == []


def test_forbidden_behavior_is_hard_fail():
    benchmark = _load_json("data/coaching_radar_ai_review_benchmark_v1.json")
    case = benchmark["cases"][0]
    review = _good_review(case)
    review["behavior_codes"].append(case["forbidden_behavior_codes"][0])
    result = score_review(review, case, benchmark["scoring"])
    assert result["pass"] is False
    assert "FORBIDDEN_BEHAVIOR_PRESENT" in result["hard_fail_reasons"]
    assert result["component_scores"]["forbidden_behavior"] == 0


def test_missing_required_behaviors_reduce_score():
    benchmark = _load_json("data/coaching_radar_ai_review_benchmark_v1.json")
    case = benchmark["cases"][0]
    review = _good_review(case)
    review["behavior_codes"] = ["COACH_DECISION_REQUIRED"]
    result = score_review(review, case, benchmark["scoring"])
    assert result["pass"] is False
    assert result["missing_required_behavior_codes"]
    assert result["score"] < benchmark["scoring"]["pass_threshold"]


def test_attention_must_match_case_calibration():
    benchmark = _load_json("data/coaching_radar_ai_review_benchmark_v1.json")
    case = next(x for x in benchmark["cases"] if x["radar_status"] == "YELLOW")
    review = _good_review(case)
    review["attention"] = "NO_REVIEW"
    result = score_review(review, case, benchmark["scoring"])
    assert result["attention_ok"] is False
    assert result["component_scores"]["attention"] == 0


def test_missing_evidence_or_uncertainty_loses_structural_points():
    benchmark = _load_json("data/coaching_radar_ai_review_benchmark_v1.json")
    case = benchmark["cases"][0]
    review = _good_review(case)
    review["observations"][0]["evidence_refs"] = []
    review["observations"][0]["uncertainty"] = ""
    result = score_review(review, case, benchmark["scoring"])
    assert result["evidence_uncertainty_ok"] is False
    assert result["component_scores"]["evidence_uncertainty"] == 0


def test_side_effect_claim_breaks_coach_restraint():
    benchmark = _load_json("data/coaching_radar_ai_review_benchmark_v1.json")
    case = benchmark["cases"][0]
    review = _good_review(case)
    review["trainingpeaks_writes"] = 1
    result = score_review(review, case, benchmark["scoring"])
    assert result["coach_restraint_ok"] is False
    assert result["component_scores"]["coach_restraint"] == 0


def test_green_case_accepts_no_review_or_coach_review_only():
    benchmark = _load_json("data/coaching_radar_ai_review_benchmark_v1.json")
    case = next(x for x in benchmark["cases"] if x["radar_status"] == "GREEN")
    assert case["acceptable_attention"] == ["NO_REVIEW", "COACH_REVIEW"]
    review = _good_review(case)
    result = score_review(review, case, benchmark["scoring"])
    assert result["pass"] is True
