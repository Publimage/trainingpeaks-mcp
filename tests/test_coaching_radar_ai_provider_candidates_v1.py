import json
from pathlib import Path


def test_provider_candidate_matrix_is_non_activating_and_paid_only():
    raw = json.loads(Path("data/coaching_radar_ai_provider_candidates_v1.json").read_text())
    assert raw["schema"] == "IRONMAN_RADAR_AI_PROVIDER_CANDIDATES_V1"
    assert raw["activation_status"] == "NOT_AUTHORIZED"
    assert raw["selection_policy"]["paid_service_activation_requires_coach_confirmation"] is True
    assert raw["selection_policy"]["no_free_tier_for_athlete_data"] is True
    assert len(raw["primary_candidates"]) == 3
    assert {x["provider"] for x in raw["primary_candidates"]} == {"OpenAI", "Anthropic", "Google"}
    for item in raw["primary_candidates"]:
        assert item["input_usd_per_million"] > 0
        assert item["output_usd_per_million"] > 0
        assert item["structured_outputs"] is True
        assert item["commercial_api_training_default"] is False
