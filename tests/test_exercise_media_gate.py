"""Regression tests for the one shared IRONMAN media gate, without TP writes."""
import pytest

from tp_mcp.tools.exercise_media_gate import (
    ExerciseMediaGateError,
    approved_media_snapshot,
    assert_exercise_description_preserved,
    assert_exercise_media_ready,
    audit_exercise_media,
    normalize_media_sport,
)


def test_approved_catalog_versioned_and_provider_surface_independent():
    catalog = approved_media_snapshot()
    assert len(catalog["resources"]) >= 9
    assert normalize_media_sport(1) == "swim"
    assert normalize_media_sport(3) == "run"
    assert normalize_media_sport("Strength") == "strength"


def test_winter_generic_native_swim_drill_is_blocked_even_with_easy_prose():
    desc = "TECNICA E INDICAZIONI\nCura respirazione, assetto e continuita."
    structure = {"structure": [{"type": "repetition", "length": {"value": 6},
                 "steps": [{"name": "Tecnica 25 m + completo 25 m"}]}]}
    result = audit_exercise_media(desc, sport="swim", surface="plan:689369",
                                  title="Tecnica | 1800 m", structure=structure)
    assert result["status"] == "BLOCK_RELEASE"
    assert "SWIM_DRILL_UNSPECIFIED" in result["issues"]


def test_explicit_swim_drill_requires_correct_approved_video():
    desc = "Esegui 2x50 Pugni chiusi (25m esercizio + 25m completo)."
    with pytest.raises(ExerciseMediaGateError, match="SWIM_FIST"):
        assert_exercise_media_ready(desc, sport="swim", surface="library")
    good = desc + "\nVideo: https://youtu.be/o0ffl059C1Q"
    report = assert_exercise_media_ready(good, sport="swim", surface="library")
    assert report["matched_uids"] == ["SWIM_FIST"]


def test_two_swim_drills_require_both_individually_approved_links():
    desc = ("2x50 Pugni chiusi, 2x50 Sculling. Video primo esercizio: "
            "https://youtu.be/o0ffl059C1Q")
    result = audit_exercise_media(desc, sport="swim", surface="library")
    assert "MEDIA_APPROVED_VIDEO_MISSING:SWIM_SCULLING" in result["issues"]


def test_run_a_march_missing_media_fails_and_canonical_video_passes():
    text = ("TECNICA E INDICAZIONI\nEsegui l'A-March (marcia tecnica) "
            "2x15m, rientrando camminando.")
    with pytest.raises(ExerciseMediaGateError, match="RUN_A_MARCH"):
        assert_exercise_media_ready(text, sport="run", surface="athlete-calendar")
    assert_exercise_media_ready(
        text + "\nVideo: https://www.youtube.com/watch?v=ErLfYSa5m7A",
        sport="run", surface="athlete-calendar",
    )


def test_multi_exercise_media_not_satisfied_by_single_unrelated_video():
    text = ("Esegui A-March e ankling. "
            "Video A-March: https://www.youtube.com/watch?v=ErLfYSa5m7A")
    result = audit_exercise_media(text, sport="run", surface="plan")
    assert "MEDIA_APPROVED_VIDEO_MISSING:RUN_ANKLING" in result["issues"]


def test_copy_integrity_preserves_full_athlete_facing_description():
    source = {"description": "Esegui A-March con il video approvato.",
              "coachComments": "Recupero camminando."}
    target = dict(source)
    assert_exercise_description_preserved(source, target, surface="library:copy")
    target["description"] = "Esegui A-March."
    with pytest.raises(ExerciseMediaGateError, match="MEDIA_DESCRIPTION_LOST"):
        assert_exercise_description_preserved(source, target,
                                              surface="library:copy")


def test_native_strength_cannot_claim_embedded_video_without_readback():
    result = audit_exercise_media(
        "Forza base", sport="strength", surface="strength-builder",
        native_exercises=[{"exercise_id": 144, "name": "Goblet Squat",
                           "video_verified": False, "variant_verified": True}],
    )
    assert result["status"] == "BLOCK_RELEASE"
    verified = audit_exercise_media(
        "Forza base", sport="strength", surface="strength-builder",
        native_exercises=[{"exercise_id": 144, "name": "Goblet Squat",
                           "video_verified": True, "variant_verified": True}],
    )
    assert verified["status"] == "PASS"


def test_nontechnical_endurance_workout_is_unaffected():
    assert_exercise_media_ready(
        "Corsa facile 35 min, respirazione regolare RPE 2-3.",
        sport="run", surface="calendar",
    )
    assert_exercise_media_ready(
        "Nuoto completo facile, 1500 metri.",
        sport="swim", surface="library",
    )


def test_explicit_unknown_resource_fails_closed():
    result = audit_exercise_media(
        "Tecnica", sport="run", surface="publisher",
        prescribed_uids=["RUN_NOT_APPROVED"],
    )
    assert "MEDIA_RESOURCE_NOT_APPROVED:RUN_NOT_APPROVED" in result["issues"]


@pytest.mark.asyncio
async def test_athlete_original_creation_blocks_unexplained_a_march_before_provider_io():
    from unittest.mock import patch
    from tp_mcp.tools.workouts import tp_create_workout

    with patch("tp_mcp.tools.workouts.TPClient") as client:
        result = await tp_create_workout(
            date_str="2027-01-04", sport="Run", title="Tecnica | 40 minuti",
            duration_minutes=40,
            description="TECNICA E INDICAZIONI\\nEsegui A-March 2x15 metri.",
        )
        assert result["error_code"] == "EXERCISE_MEDIA_NOT_READY"
        client.assert_not_called()


@pytest.mark.asyncio
async def test_library_item_creation_blocks_generic_swim_builder_before_provider_io():
    from unittest.mock import patch
    from tp_mcp.tools.library import tp_create_library_item

    with patch("tp_mcp.tools.library.TPClient") as client:
        result = await tp_create_library_item(
            library_id="123", name="Tecnica | 1800 metri",
            sport_family_id=1, sport_type_id=1, duration_hours=0.7,
            description="Nuoto facile e controllato.",
            structure={"structure":[{"type":"repetition","length":{"value":6},
                                     "steps":[{"name":"Tecnica 25 m + completo 25 m"}]}]},
        )
        assert result["error_code"] == "EXERCISE_MEDIA_NOT_READY"
        client.assert_not_called()


def test_library_to_athlete_schedule_applies_same_gate():
    from tp_mcp.tools.library import _template_workout_payload

    item = {
        "itemName": "Tecnica nuoto", "workoutTypeId": 1,
        "description": "Nuota 6x50 facile",
        "structure": {"structure": [{"type": "repetition", "length": {"value": 6},
                                     "steps": [{"name": "Tecnica 25 m + completo 25 m"}]}]},
    }
    with pytest.raises(ExerciseMediaGateError, match="SWIM_DRILL_UNSPECIFIED"):
        _template_workout_payload(item, "2027-01-04", 123)


def test_original_strength_workout_uses_same_media_gate():
    from unittest.mock import patch
    from tp_mcp.tools.strength import _assert_native_strength_media

    blocks = [{"exercises": [{"id": "144", "sets": [{"Reps": 8}]}]}]
    snapshot = {"144": {"id": "144", "title": "Goblet Squat",
                        "videoUrl": "https://video.trainingpeaks.example/goblet"}}
    with patch("tp_mcp.tools.strength._catalogue", return_value=snapshot):
        _assert_native_strength_media(blocks)
    snapshot["144"]["videoUrl"] = None
    with patch("tp_mcp.tools.strength._catalogue", return_value=snapshot):
        with pytest.raises(ExerciseMediaGateError, match="NATIVE_EXERCISE_VIDEO"):
            _assert_native_strength_media(blocks)


def test_shared_training_plan_publisher_blocks_missing_drill_media():
    from scripts.ironman_jobs.reviewed_plan_patch_pipeline import validate_reviewed_media_delta

    source = {
        "workoutTypeValueId": 1,
        "title": "Tecnica | 1800 metri",
        "description": "Nuoto facile.",
        "structure": {"structure": [
            {"type": "repetition", "length": {"value": 6},
             "steps": [{"name": "Tecnica 25 m + completo 25 m"}]},
        ]},
    }
    with pytest.raises(ExerciseMediaGateError, match="SWIM_DRILL_UNSPECIFIED"):
        validate_reviewed_media_delta(
            source, {"description": "Nuoto facile, verifica la presa."},
            surface="training-plan:preview",
        )
    # An unrelated reviewed change must not retroactively block an existing
    # workout before its exercise content is independently repaired.
    validate_reviewed_media_delta(
        source, {"totalTimePlanned": 0.7}, surface="training-plan:preview",
    )
