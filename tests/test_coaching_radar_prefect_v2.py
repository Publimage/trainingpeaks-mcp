import json
from pathlib import Path
import importlib.util


def load_module():
    p = Path("scripts/ironman_jobs/coaching_radar_prefect_v2.py")
    spec = importlib.util.spec_from_file_location("coaching_radar_prefect_v2", p)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_active_roster_is_ten_and_excludes_marco():
    raw = json.loads(Path("data/coaching_radar_alberto_group_v1.json").read_text())
    enabled = [x for x in raw["athletes"] if x["enabled"]]
    assert len(enabled) == 10
    assert 3737499 not in {x["athlete_id"] for x in enabled}
    assert 2932097 in {x["athlete_id"] for x in enabled}


def test_group_pipeline_is_read_only_and_sequential():
    text = Path("scripts/ironman_jobs/coaching_radar_prefect_v2.py").read_text()
    assert "trainingpeaks_writes" in text
    assert "for athlete_id in selected:" in text
    assert "GROUP_RADAR_PARTIAL_FAILURE" in text
    assert "create_workout" not in text
    assert "update_workout" not in text
    assert "delete_workout" not in text


def test_schedule_transition_is_daily_rome_0530():
    text = Path("prefect/ironman-coaching-radar-v2.yaml").read_text()
    assert text.count('cron: "30 5 * * *"') == 2
    assert text.count('timezone: "Europe/Rome"') == 2
    assert "polverari-readonly-daily-v2" in text
    assert "alberto-group-readonly-daily" in text
    assert "active: true" in text
    assert "active: false" in text
    assert "2932097" in text


def test_as_of_defaults_to_local_date():
    mod = load_module()
    assert mod._resolved_as_of("2026-10-17") == "2026-10-17"
