from scripts.ironman_jobs.estimate_coaching_radar_ai_provider_costs_v1 import estimate


def test_cost_estimate_uses_payload_bounds_and_output_assumption():
    summary = {
        "case_count": 10,
        "approx_input_tokens_typical_chars4": 50000,
        "approx_input_tokens_conservative_chars3": 70000,
    }
    candidates = {
        "primary_candidates": [{
            "provider": "P",
            "model": "M",
            "input_usd_per_million": 2.0,
            "output_usd_per_million": 10.0,
        }],
        "ceiling_candidates": [],
        "economy_candidates": [],
    }
    result = estimate(summary, candidates, output_tokens_per_case=1000, days=30)
    row = result["rows"][0]
    assert result["output_tokens_total_assumption"] == 10000
    assert row["benchmark_run_typical_usd"] == 0.2
    assert row["benchmark_run_conservative_usd"] == 0.24
    assert row["monthly_typical_usd"] == 6.0
    assert result["ai_calls"] == 0
