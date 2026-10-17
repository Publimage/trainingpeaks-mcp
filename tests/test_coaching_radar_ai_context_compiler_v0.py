import copy

from scripts.ironman_jobs.coaching_radar_ai_context_compiler_v0 import (
    compile_selective_context,
    evaluate_compiled_context,
)


def _packet(categories=None, missing_rpe=True, wellness=0):
    categories = ["TSS_DATA_QUALITY"] if categories is None else categories
    roles = [
        "core_index",
        "master_coaching_context",
        "decision_log",
        "open_questions_roadmap",
        "athlete_card",
        "workstream_state",
    ]
    contents = {
        "core_index": "# Fonte canonica\nLa Knowledge Base e' la source of truth.",
        "master_coaching_context": "# Decisioni\nAI organizza e analizza; il coach decide. Usare evidenze e incertezza.\n# Dati\nTSS, IF, soglie, sensori e RPE vanno letti insieme.",
        "decision_log": "# Regole\nNon inferire automaticamente sovraccarico da un singolo TSS.",
        "open_questions_roadmap": "# Qualita dati\nVerificare regressioni e dati mancanti.",
        "athlete_card": "# Profilo\nTrainingPeaks ID: 2932097\n# Dati atleta\nNon basare decisioni solo sul TSS; verificare durata, ritmo, potenza, frequenza cardiaca e struttura reale.",
        "workstream_state": "# Radar\nREAD_ONLY; nessuna scrittura provider.",
        "specialist:0": "# Coaching diretto\nIl piano deve essere adattato alla vita reale, monitorabile e sostenibile. Feedback e recupero contano.",
    }
    source_index = {r: {
        "title": r,
        "document_id": "id-" + r,
        "source_version": "1",
        "content_sha256": ("a" * 64),
    } for r in roles}
    source_index["specialist_documents"] = [{
        "title": "protocol",
        "document_id": "id-protocol",
        "source_version": "1",
        "content_sha256": "b" * 64,
    }]
    alerts = [{"category": c, "sport": "Run"} for c in categories]
    return {
        "schema": "IRONMAN_COACHING_RADAR_AI_INPUT_V1",
        "mode": "SHADOW_READ_ONLY",
        "athlete_id": 2932097,
        "athlete_name": "Athlete",
        "as_of": "2026-10-17",
        "input_fingerprint_sha256": "d" * 64,
        "radar": {
            "alerts": alerts,
            "upcoming": [{"sport": "Bike", "title": "Endurance"}],
            "data_quality": {
                "wellness_metrics_count": wellness,
                "missing_rpe_workout_ids": ["1"] if missing_rpe else [],
            },
            "evidence_sha256": "e" * 64,
        },
        "knowledge_base": {
            "context_fingerprint_sha256": "f" * 64,
            "source_index": source_index,
            "contents": contents,
        },
    }


def test_compiler_is_deterministic_and_bounded():
    packet = _packet(["TSS_DATA_QUALITY", "IF_DATA_QUALITY"])
    a = compile_selective_context(packet, max_total_chars=6000)
    b = compile_selective_context(copy.deepcopy(packet), max_total_chars=6000)
    assert a == b
    assert a["selected_char_count"] <= 6000
    assert a["ai_calls"] == 0
    assert a["trainingpeaks_writes"] == 0
    assert a["drive_writes"] == 0


def test_compiler_requires_athlete_master_and_specialist():
    compiled = compile_selective_context(_packet(), max_total_chars=6000)
    roles = {x["role"] for x in compiled["excerpts"]}
    assert "athlete_card" in roles
    assert "master_coaching_context" in roles
    assert any(x.startswith("specialist:") for x in roles)


def test_tss_and_if_signals_select_data_quality_context():
    compiled = compile_selective_context(_packet(["TSS_DATA_QUALITY", "IF_DATA_QUALITY"]), max_total_chars=6000)
    joined = "\n".join(x["excerpt"].lower() for x in compiled["excerpts"])
    assert "tss" in joined
    assert "soglie" in joined or "soglia" in joined
    assert "rpe" in joined


def test_completion_signal_adds_absence_feedback_terms():
    compiled = compile_selective_context(_packet(["COMPLETION_UNCONFIRMED"]), max_total_chars=6000)
    assert "completion_unconfirmed" in compiled["signal_categories"]
    terms = set(compiled["selection_terms"])
    assert "feedback" in terms
    assert "assenza" in terms


def test_duration_short_signal_is_preserved():
    compiled = compile_selective_context(_packet(["DURATION_SHORT"]), max_total_chars=6000)
    assert compiled["signal_categories"] == ["DURATION_SHORT"]


def test_no_alert_but_missing_feedback_still_compiles_policy_context():
    compiled = compile_selective_context(_packet([], missing_rpe=True, wellness=0), max_total_chars=6000)
    assert compiled["signal_categories"] == []\n    assert "feedback" in compiled["selection_terms"]\n    assert "wellness" in compiled["selection_terms"]


def test_eval_passes_expected_current_radar_routing():
    compiled = compile_selective_context(_packet(["TSS_DATA_QUALITY", "IF_DATA_QUALITY"]), max_total_chars=6000)
    result = evaluate_compiled_context(
        compiled,
        expected_categories=["TSS_DATA_QUALITY", "IF_DATA_QUALITY"],
        expected_role_families=["athlete_card", "master_coaching_context", "specialist"],
        max_chars=6000,
    )
    assert result["pass"] is True


def test_eval_fails_missing_expected_signal():
    compiled = compile_selective_context(_packet(["DURATION_SHORT"]), max_total_chars=6000)
    result = evaluate_compiled_context(
        compiled,
        expected_categories=["DURATION_SHORT", "COMPLETION_UNCONFIRMED"],
        expected_role_families=["athlete_card", "master_coaching_context", "specialist"],
        max_chars=6000,
    )
    assert result["pass"] is False
    assert result["missing_categories"] == ["COMPLETION_UNCONFIRMED"]


def test_short_term_if_does_not_match_inside_verificare():
    packet = _packet(["IF_DATA_QUALITY"])
    packet["knowledge_base"]["contents"]["decision_log"] = "# Controllo\nVerificare i dati prima della decisione."
    compiled = compile_selective_context(packet, max_total_chars=6000)
    decision = [x for x in compiled["excerpts"] if x["role"] == "decision_log"]
    if decision:
        assert "if" not in decision[0]["matched_terms"]
