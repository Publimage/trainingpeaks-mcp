"""Estimate Radar AI benchmark and daily costs before provider activation.

Uses privacy-minimized payload size estimates and public candidate token prices.
No provider/network calls. Output-token assumptions are explicit parameters.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def estimate(summary, candidates, *, output_tokens_per_case: int, days: int):
    case_count = int(summary["case_count"])
    input_typical = int(summary["approx_input_tokens_typical_chars4"])
    input_conservative = int(summary["approx_input_tokens_conservative_chars3"])
    output_total = output_tokens_per_case * case_count

    rows = []
    groups = (
        ("PRIMARY", candidates.get("primary_candidates") or []),
        ("CEILING", candidates.get("ceiling_candidates") or []),
        ("ECONOMY", candidates.get("economy_candidates") or []),
    )
    for group, models in groups:
        for model in models:
            inp = float(model["input_usd_per_million"])
            out = float(model["output_usd_per_million"])
            typical_run = input_typical / 1_000_000 * inp + output_total / 1_000_000 * out
            conservative_run = input_conservative / 1_000_000 * inp + output_total / 1_000_000 * out
            rows.append({
                "group": group,
                "provider": model["provider"],
                "model": model["model"],
                "input_usd_per_million": inp,
                "output_usd_per_million": out,
                "output_tokens_per_case_assumption": output_tokens_per_case,
                "benchmark_run_typical_usd": round(typical_run, 6),
                "benchmark_run_conservative_usd": round(conservative_run, 6),
                "daily_10_athletes_typical_usd": round(typical_run, 6),
                "monthly_typical_usd": round(typical_run * days, 4),
                "monthly_conservative_usd": round(conservative_run * days, 4),
                "pricing_note": model.get("pricing_note"),
            })
    return {
        "schema": "IRONMAN_RADAR_AI_PROVIDER_COST_ESTIMATE_V1",
        "case_count": case_count,
        "input_tokens_typical_estimate": input_typical,
        "input_tokens_conservative_estimate": input_conservative,
        "output_tokens_total_assumption": output_total,
        "days_per_month_assumption": days,
        "rows": rows,
        "ai_calls": 0,
        "gate": "ESTIMATE_ONLY",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload-summary", required=True)
    parser.add_argument("--candidates-file", required=True)
    parser.add_argument("--output-tokens-per-case", type=int, default=1000)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    if args.output_tokens_per_case <= 0 or args.days <= 0:
        raise SystemExit("INVALID_COST_ASSUMPTION")
    summary = json.loads(Path(args.payload_summary).read_text(encoding="utf-8"))
    candidates = json.loads(Path(args.candidates_file).read_text(encoding="utf-8"))
    result = estimate(
        summary,
        candidates,
        output_tokens_per_case=args.output_tokens_per_case,
        days=args.days,
    )
    print("RADAR_AI_PROVIDER_COST_ESTIMATE")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
