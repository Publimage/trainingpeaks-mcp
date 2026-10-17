"""Validate the committed Radar AI context-routing evaluation cases.

No provider calls. The file is a privacy-minimized routing snapshot: athlete ID,
signal categories, data-quality flags and expected topics only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.ironman_jobs.coaching_radar_ai_context_compiler_v0 import (
    CATEGORY_TERMS,
    DATA_QUALITY_FLAG_TERMS,
)

SCHEMA = "IRONMAN_RADAR_AI_CONTEXT_EVAL_CASES_V1"
ROSTER = Path(__file__).resolve().parents[2] / "data" / "coaching_radar_alberto_group_v1.json"


def validate_cases(path: Path, roster_path: Path = ROSTER) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema") != SCHEMA:
        raise ValueError("AI_CONTEXT_EVAL_SCHEMA_MISMATCH")
    if raw.get("trainingpeaks_writes") != 0 or raw.get("drive_writes") != 0 or raw.get("ai_calls") != 0:
        raise ValueError("AI_CONTEXT_EVAL_SIDE_EFFECT_GUARD_FAILED")

    roster_raw = json.loads(roster_path.read_text(encoding="utf-8"))
    active = {int(x["athlete_id"]) for x in roster_raw["athletes"] if x.get("enabled")}
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("AI_CONTEXT_EVAL_CASES_MISSING")

    seen: set[int] = set()
    unsupported: set[str] = set()
    unsupported_data_quality: set[str] = set()
    for item in cases:
        athlete_id = int(item["athlete_id"])
        if athlete_id not in active:
            raise ValueError(f"AI_CONTEXT_EVAL_ATHLETE_NOT_ACTIVE:{athlete_id}")
        if athlete_id in seen:
            raise ValueError(f"AI_CONTEXT_EVAL_DUPLICATE_ATHLETE:{athlete_id}")
        seen.add(athlete_id)
        categories = item.get("categories")
        if not isinstance(categories, list):
            raise ValueError("AI_CONTEXT_EVAL_CATEGORIES_INVALID")
        for category in categories:
            if category not in CATEGORY_TERMS:
                unsupported.add(str(category))
        flags = item.get("data_quality")
        if not isinstance(flags, list) or not flags:
            raise ValueError("AI_CONTEXT_EVAL_DATA_QUALITY_FLAGS_MISSING")
        for flag in flags:
            if flag not in DATA_QUALITY_FLAG_TERMS:
                unsupported_data_quality.add(str(flag))
        if not isinstance(item.get("expected_topics"), list) or not item["expected_topics"]:
            raise ValueError("AI_CONTEXT_EVAL_EXPECTED_TOPICS_MISSING")

    if seen != active:
        missing = sorted(active - seen)
        raise ValueError("AI_CONTEXT_EVAL_ROSTER_INCOMPLETE:" + ",".join(map(str, missing)))
    if unsupported:
        raise ValueError("AI_CONTEXT_EVAL_UNSUPPORTED_CATEGORY:" + ",".join(sorted(unsupported)))
    if unsupported_data_quality:
        raise ValueError(
            "AI_CONTEXT_EVAL_UNSUPPORTED_DATA_QUALITY:"
            + ",".join(sorted(unsupported_data_quality))
        )

    category_counts: dict[str, int] = {}
    for item in cases:
        for category in item["categories"]:
            category_counts[category] = category_counts.get(category, 0) + 1

    return {
        "schema": SCHEMA,
        "case_count": len(cases),
        "active_roster_count": len(active),
        "category_counts": dict(sorted(category_counts.items())),
        "zero_alert_cases": sum(1 for x in cases if not x["categories"]),
        "trainingpeaks_writes": 0,
        "drive_writes": 0,
        "ai_calls": 0,
        "gate": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases-file", required=True)
    args = parser.parse_args()
    result = validate_cases(Path(args.cases_file))
    print("RADAR_AI_CONTEXT_EVAL_CASES_PASS")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
