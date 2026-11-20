"""Offline regression tests for archive-to-Workout-Library structure adapter."""
import pytest

from tp_mcp.tools.archive_structure_adapter import (
    ArchiveStructureError, convert_archive_structure,
)


def step(name, value, unit, low, high, intensity_class="active"):
    return {
        "type": "step", "name": name,
        "length": {"value": value, "unit": unit},
        "intensityMin": low, "intensityMax": high,
        "intensityClass": intensity_class,
    }


def test_bike_3x10_subthreshold_70min():
    archive = {
        "primaryLengthMetric": "duration",
        "primaryIntensityMetric": "percentOfFtp",
        "steps": [
            step("Riscaldamento", 900, "second", 50, 65, "warmUp"),
            {"type": "repetition", "name": "3x10 subthreshold", "reps": 3, "steps": [
                step("Lavoro", 600, "second", 85, 90),
                step("Recupero", 300, "second", 50, 60, "rest"),
            ]},
            step("Defaticamento", 600, "second", 45, 55, "coolDown"),
        ],
    }
    got = convert_archive_structure(archive, expected_primary_total=4200)
    assert got["primaryIntensityMetric"] == "percentOfFtp"
    assert len(got["structure"]) == 3
    assert got["structure"][1]["length"] == {"value": 3, "unit": "repetition"}
    assert got["structure"][1]["steps"][0]["targets"] == [{"minValue": 85, "maxValue": 90}]


def test_swim_2500_meters():
    archive = {
        "primaryLengthMetric": "distance",
        "visualizationDistanceUnit": "meter",
        "primaryIntensityMetric": "percentOfThresholdPace",
        "steps": [
            step("Warm-up", 500, "meter", 80, 87, "warmUp"),
            {"type": "repetition", "reps": 4, "steps": [
                step("Endurance", 400, "meter", 86, 92)]},
            step("Cool-down", 400, "meter", 78, 85, "coolDown"),
        ],
    }
    got = convert_archive_structure(archive, expected_primary_total=2500)
    assert got["visualizationDistanceUnit"] == "meter"
    assert got["structure"][1]["length"]["value"] == 4
    assert got["structure"][1]["steps"][0]["length"]["unit"] == "meter"


def test_swim_distance_ignores_seconds_recovery_only_after_explicit_opt_in():
    archive = {
        "primaryLengthMetric": "distance",
        "primaryIntensityMetric": "percentOfThresholdPace",
        "steps": [{"type": "repetition", "reps": 4, "steps": [
            step("Swim", 500, "meter", 86, 94),
            step("Recovery", 25, "second", 0, 0, "rest"),
        ]}],
    }
    with pytest.raises(ArchiveStructureError, match="Mixed"):
        convert_archive_structure(archive, expected_primary_total=2000)
    got = convert_archive_structure(
        archive, expected_primary_total=2000, allow_mixed_length_units=True
    )
    assert got["structure"][0]["steps"][1]["length"]["unit"] == "second"


def test_fail_closed_total_and_bad_targets():
    archive = {
        "primaryLengthMetric": "duration", "primaryIntensityMetric": "rpe",
        "steps": [step("Run", 1800, "second", 2, 3)],
    }
    with pytest.raises(ArchiveStructureError, match="expected"):
        convert_archive_structure(archive, expected_primary_total=3000)
    archive["steps"][0]["intensityMin"] = 9
    with pytest.raises(ArchiveStructureError, match="Intensity"):
        convert_archive_structure(archive)
