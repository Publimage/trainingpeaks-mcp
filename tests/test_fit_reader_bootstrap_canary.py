from pathlib import Path


def test_fit_bootstrap_is_pinned_and_scoped():
    text = Path("scripts/ironman_jobs/fit_reader_bootstrap_canary.py").read_text(encoding="utf-8")
    assert 'FITDECODE_PIN = "fitdecode==0.11.0"' in text
    assert 'ATHLETE_ID = "4480273"' in text
    assert '"4007650256"' in text
    assert '"4007654126"' in text
    assert '"4007650672"' in text
    assert "tp_get_workout_fit_data" in text
