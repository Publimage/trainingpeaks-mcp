from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ironman_jobs.coaching_radar_prefect_v1 import (
    _window,
    build_report,
    persist_bundle,
)


def sample_raw():
    return {
        "schema": "IRONMAN_TP_RADAR_INPUT_V1",
        "athlete_id": 2932097,
        "start_date": "2026-10-13",
        "end_date": "2026-10-19",
        "fetched_at_utc": "2026-10-16T05:00:00+00:00",
        "trainingpeaks_writes": 0,
        "metrics": {"metrics": [], "count": 0},
        "workouts": [
            {
                "id": "3997494824",
                "date": "2026-10-15",
                "sport": "Run",
                "type": "completed",
                "title": "Corsa - Easy | 35'",
                "duration_planned": 35 / 60,
                "duration_actual": 35.19 / 60,
                "tss_planned": 44.99,
                "tss_actual": 118.79,
            },
            {
                "id": "future-1",
                "date": "2026-10-17",
                "sport": "Run",
                "type": "planned",
                "title": "Lungo",
            },
        ],
        "completed_details": [
            {
                "id": "3997494824",
                "rpe": 2,
                "metrics": {
                    "duration_planned": 35 / 60,
                    "duration_actual": 35.19 / 60,
                    "tss_planned": 44.99,
                    "tss_actual": 118.79,
                    "if_planned": 0.84,
                    "if_actual": 1.4323,
                },
            }
        ],
    }


def test_report_flags_data_quality_not_overload():
    report = build_report(sample_raw(), "2026-10-16")
    cats = {x["category"] for x in report["alerts"]}
    assert "TSS_DATA_QUALITY" in cats
    assert "IF_DATA_QUALITY" in cats
    assert report["status"] == "YELLOW"
    assert report["trainingpeaks_writes"] == 0
    assert report["upcoming"][0]["workout_id"] == "future-1"


def test_window_bounds():
    assert _window("2026-10-16", 3, 3) == ("2026-10-13", "2026-10-19")
    with pytest.raises(ValueError):
        _window("2026-10-16", 15, 3)


def test_persist_bundle_is_atomic_shape(tmp_path: Path):
    raw = sample_raw()
    report = build_report(raw, "2026-10-16")
    paths = persist_bundle(raw, report, tmp_path)
    assert Path(paths["input"]).exists()
    assert Path(paths["report"]).exists()
    assert Path(paths["latest"]).exists()
    assert Path(paths["latest"]).read_text().find("IRONMAN_COACHING_RADAR_V1") >= 0


def test_wrong_athlete_stops():
    raw = sample_raw()
    raw["athlete_id"] = 999
    with pytest.raises(ValueError, match="PILOT_ATHLETE_ID_MISMATCH"):
        build_report(raw, "2026-10-16")
