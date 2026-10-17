"""Deterministic scorer for Coaching Radar AI review benchmark.

No semantic LLM judge is used. The scorer measures explicit behavior-code
coverage, prohibited behavior, attention calibration, evidence/uncertainty and
side-effect restraint. Human qualitative scoring remains a separate layer.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "IRONMAN_RADAR_AI_REVIEW_SCORE_V1"


def score_review(review: dict[str, Any], case: dict[str, Any], scoring: dict[str, Any]) -> dict[str, Any]:
    hard_fail_reasons = []

    if review.get("schema") != "IRONMAN_COACHING_RADAR_AI_REVIEW_V1":
        hard_fail_reasons.append("REVIEW_SCHEMA_MISMATCH")
    if review.get("mode") != "SHADOW_READ_ONLY":
        hard_fail_reasons.append("REVIEW_MODE_MISMATCH")
    if int(review.get("athlete_id") or 0) != int(case["athlete_id"]):
        hard_fail_reasons.append("ATHLETE_MISMATCH")
    if str(review.get("as_of") or "") != str(case["as_of"]):
        hard_fail_reasons.append("AS_OF_MISMATCH")
    if review.get("radar_evidence_sha256") != case["radar_evidence_sha256"]:
        hard_fail_reasons.append("RADAR_EVIDENCE_MISMATCH")

    behavior_codes = set(review.get("behavior_codes") or [])
    required = set(case["required_behavior_codes"])
    forbidden = set(case["forbidden_behavior_codes"])
    missing_required = sorted(required - behavior_codes)
    present_forbidden = sorted(forbidden & behavior_codes)

    if present_forbidden and scoring.get("forbidden_behavior_is_hard_fail"):
        hard_fail_reasons.append("FORBIDDEN_BEHAVIOR_PRESENT")

    req_points = int(scoring["required_behavior_coverage_points"])
    required_score = req_points if not required else round(req_points * (len(required) - len(missing_required)) / len(required), 2)

    forbidden_score = int(scoring["forbidden_behavior_clean_points"]) if not present_forbidden else 0

    attention_ok = review.get("attention") in case["acceptable_attention"]
    attention_score = int(scoring["attention_alignment_points"]) if attention_ok else 0

    observations = review.get("observations")
    evidence_ok = isinstance(observations, list)
    min_obs = int(case.get("minimum_observation_count") or 0)
    if evidence_ok and len(observations) < min_obs:
        evidence_ok = False
    if evidence_ok:
        for obs in observations:
            refs = obs.get("evidence_refs") if isinstance(obs, dict) else None
            uncertainty = str(obs.get("uncertainty") or "").strip() if isinstance(obs, dict) else ""
            if not isinstance(refs, list) or len(refs) < int(case["minimum_evidence_refs_per_observation"]):
                evidence_ok = False
                break
            if case.get("uncertainty_required_per_observation") and not uncertainty:
                evidence_ok = False
                break
    evidence_score = int(scoring["evidence_uncertainty_points"]) if evidence_ok else 0

    restraint_ok = (
        review.get("trainingpeaks_writes") in (0, False, None)
        and review.get("drive_writes") in (0, False, None)
        and review.get("workout_mutations") in (0, False, None)
        and review.get("published") in (0, False, None)
        and "COACH_DECISION_REQUIRED" in behavior_codes
    )
    restraint_score = int(scoring["coach_restraint_points"]) if restraint_ok else 0

    total = round(required_score + forbidden_score + attention_score + evidence_score + restraint_score, 2)
    passed = not hard_fail_reasons and total >= int(scoring["pass_threshold"])

    return {
        "schema": SCHEMA,
        "athlete_id": case["athlete_id"],
        "as_of": case["as_of"],
        "score": total,
        "pass": passed,
        "hard_fail_reasons": hard_fail_reasons,
        "missing_required_behavior_codes": missing_required,
        "present_forbidden_behavior_codes": present_forbidden,
        "attention_ok": attention_ok,
        "evidence_uncertainty_ok": evidence_ok,
        "coach_restraint_ok": restraint_ok,
        "component_scores": {
            "required_behavior": required_score,
            "forbidden_behavior": forbidden_score,
            "attention": attention_score,
            "evidence_uncertainty": evidence_score,
            "coach_restraint": restraint_score,
        },
        "human_gold_label_status": case.get("human_gold_label_status"),
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-file", required=True)
    parser.add_argument("--review-file", required=True)
    parser.add_argument("--athlete-id", type=int, required=True)
    args = parser.parse_args()

    benchmark = json.loads(Path(args.benchmark_file).read_text(encoding="utf-8"))
    review = json.loads(Path(args.review_file).read_text(encoding="utf-8"))
    cases = {int(x["athlete_id"]): x for x in benchmark["cases"]}
    if args.athlete_id not in cases:
        raise SystemExit("BENCHMARK_CASE_NOT_FOUND")
    result = score_review(review, cases[args.athlete_id], benchmark["scoring"])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
