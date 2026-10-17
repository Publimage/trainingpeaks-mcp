import json
import stat
from pathlib import Path

from scripts.ironman_jobs.materialize_coaching_radar_ai_provider_payloads_v1 import materialize


def _private_case():
    return {
        "schema": "IRONMAN_RADAR_AI_PRIVATE_BENCHMARK_CASE_V1",
        "athlete_id": 2932097,
        "athlete_name": "Massimiliano Polverari",
        "as_of": "2026-10-17",
        "radar": {
            "status": "YELLOW",
            "review_required": True,
            "evidence_sha256": "a" * 64,
            "alerts": [{"category": "TSS_DATA_QUALITY", "workout_id": "1"}],
            "upcoming": [],
            "data_quality": {},
        },
        "selective_context": {
            "context_fingerprint_sha256": "b" * 64,
            "compiled_fingerprint_sha256": "c" * 64,
            "excerpts": [{
                "role": "athlete_card",
                "section_heading": "Profilo",
                "matched_terms": ["tss"],
                "excerpt": "Massimiliano Polverari TrainingPeaks ID: 2932097",
                "excerpt_sha256": "d" * 64,
            }],
        },
        "benchmark_expectations": {
            "required_behavior_codes": ["COACH_DECISION_REQUIRED"],
            "forbidden_behavior_codes": ["AUTOMATIC_TRAININGPEAKS_WRITE"],
            "acceptable_attention": ["COACH_REVIEW"],
        },
    }


def test_materializer_creates_private_sanitized_payloads(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    case = private / "case_2932097.json"
    case.write_text(json.dumps(_private_case()))
    case.chmod(0o600)
    manifest = {
        "gate": "PASS",
        "case_count": 10,
        "cases": [{"filename": "case_2932097.json"}] * 10,
    }
    (private / "manifest.json").write_text(json.dumps(manifest))
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object"}))
    out = tmp_path / "out"
    result = materialize(private, out, schema)
    assert result["case_count"] == 10
    assert result["gate"] == "PASS"
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    payload_files = list(out.glob("provider_*.json"))
    assert len(payload_files) == 1
    assert stat.S_IMODE(payload_files[0].stat().st_mode) == 0o600
    text = payload_files[0].read_text().lower()
    assert "massimiliano polverari" not in text
    assert "2932097" not in text
    assert result["ai_calls"] == 0


def test_summary_has_token_planning_bounds(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    (private / "case.json").write_text(json.dumps(_private_case()))
    (private / "manifest.json").write_text(json.dumps({
        "gate": "PASS",
        "case_count": 10,
        "cases": [{"filename": "case.json"}] * 10,
    }))
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object"}))
    result = materialize(private, tmp_path / "out", schema)
    assert result["approx_input_tokens_typical_chars4"] > 0
    assert result["approx_input_tokens_conservative_chars3"] >= result["approx_input_tokens_typical_chars4"]
