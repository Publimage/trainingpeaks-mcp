from pathlib import Path

def test_beginner_strength_duration_job_is_bounded():
    code = Path("scripts/ironman_jobs/beginner_strength_native_duration_20261017.py").read_text()
    assert "PLAN = 679801" in code
    assert "PERSON = 6644899" in code
    assert "EXPECTED_NATIVE = 36" in code
    assert "EXPECTED_MINUTES = 894" in code
    assert "beginner679801_strength_builder_20261016_before.json" in code
    assert 'payload["prescribedDurationInSeconds"] = target' in code
    assert "/rx/activity/v1/plans/{PLAN}/workouts/save" in code
    assert "scrub(after) == scrub(before)" in code
    assert "h.delete(" not in code
    assert "tp_update_workout" not in code
