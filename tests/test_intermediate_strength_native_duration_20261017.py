from pathlib import Path

def test_intermediate_strength_duration_job_bounded():
    code=Path("scripts/ironman_jobs/intermediate_strength_native_duration_20261017.py").read_text()
    assert "PLAN=684602" in code
    assert "PERSON=6678583" in code
    assert "EXPECTED_COUNT=259" in code
    assert "EXPECTED_NATIVE=30" in code
    assert "EXPECTED_MINUTES=750" in code
    assert 'payload["prescribedDurationInSeconds"]=target' in code
    assert "/rx/activity/v1/plans/{PLAN}/workouts/save" in code
    assert "semantic(after)==semantic(before)" in code
    assert "h.delete(" not in code
