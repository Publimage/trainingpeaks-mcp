from pathlib import Path


def test_v2_staged_installer_deploys_both_but_verifies_pilot():
    text = Path("scripts/ironman_jobs/install_coaching_radar_v2_staging_20261017.sh").read_text()
    assert "polverari-readonly-daily-v2" in text
    assert "alberto-group-readonly-daily" in text
    assert "verify_coaching_radar_v2_pilot_staging_20261017.py" in text
    assert "COACHING_RADAR_V2_STAGED_INSTALL_PASS" in text


def test_v2_pilot_verifier_is_single_athlete():
    text = Path("scripts/ironman_jobs/verify_coaching_radar_v2_pilot_staging_20261017.py").read_text()
    assert "2932097" in text
    assert "athlete_count_completed" in text
    assert "trainingpeaks_writes" in text


def test_v2_pilot_verifier_checks_schedule_states():
    text = Path("scripts/ironman_jobs/verify_coaching_radar_v2_pilot_staging_20261017.py").read_text()
    assert "RADAR_V2_PILOT_SCHEDULE_NOT_ACTIVE" in text
    assert "RADAR_V2_GROUP_SCHEDULE_NOT_INACTIVE" in text
    assert '"30 5 * * *"' in text
    assert '"Europe/Rome"' in text
