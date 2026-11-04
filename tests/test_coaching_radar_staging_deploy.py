from pathlib import Path


def test_prefect_radar_deploy_assets_are_readonly_scoped():
    yml = Path("prefect/ironman-coaching-radar-v1.yaml").read_text()
    script = Path("scripts/ironman_jobs/install_coaching_radar_staging_20261016.sh").read_text()
    assert "ironman-prefect-staging-process" in yml
    assert "2932097" in yml
    assert "10.114.0.2:8787" in yml
    assert "git checkout --detach" in script
    assert "COACHING_RADAR_STAGING_INSTALL_PASS" in script
    assert "TrainingPeaks" not in script
