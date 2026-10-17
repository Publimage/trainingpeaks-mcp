from pathlib import Path

def test_beginner_strength_duration_job_is_bounded():
    code = Path("scripts/ironman_jobs/beginner_strength_native_duration_20261017.py").read_text()
    assert "PLAN = 679801" in code
    assert "PERSON = 6644899" in code
    assert "EXPECTED_NATIVE = 36" in code
    assert "EXPECTED_MINUTES = 895" in code
    assert "beginner679801_strength_builder_20261016_before.json" in code
    assert 'payload["prescribedDurationInSeconds"] = target' in code
    assert "/rx/activity/v1/plans/{PLAN}/workouts/save" in code
    assert "scrub(after) == scrub(before)" in code
    assert "h.delete(" not in code
    assert "tp_update_workout" not in code


def test_job_has_executable_entrypoint_and_recovery_guard():
    code = Path("scripts/ironman_jobs/beginner_strength_native_duration_20261017.py").read_text()
    assert "import re" in code
    assert 'if __name__ == "__main__":' in code
    assert "asyncio.run(main())" in code
    assert "EXPECTED_MINUTES_DRIFT_" in code
    assert 'source = "native_title_duration_labels"' in code


def test_title_duration_regex_examples():
    import re
    pat = re.compile(r"(\d+)(?:-(\d+))?'")
    cases = {
        "Forza | Base 25' A": 25,
        "Forza | Neurale 25-30' A": 30,
        "Forza | Attivazione 15-20'": 20,
        "Forza | Attivazione 12'": 12,
    }
    for title, expected in cases.items():
        m = pat.search(title)
        assert m
        assert int(m.group(2) or m.group(1)) == expected


def test_historical_duration_guards():
    code = Path("scripts/ironman_jobs/beginner_strength_native_duration_20261017.py").read_text()
    assert 'title == "Forza | Attivazione 15-20\'"' in code
    assert "minutes = 18" in code
    assert "weekly_expected = [50,50,60,50,60,60,60,50,55,55,50,20,45,45,25,20,25,25,20,20,20,18,12,0]" in code
