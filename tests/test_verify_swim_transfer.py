"""Regression tests for read-only structured swim transfer comparison."""

from copy import deepcopy

from scripts.verify_swim_transfer import check


def fixture_pair():
    def step(name, amount, unit, intensity_class="active"):
        return {
            "name": name, "length": {"value": amount, "unit": unit},
            "intensityClass": intensity_class, "targets": [],
        }

    structure = {
        "primaryLengthMetric": "distance",
        "primaryIntensityMetric": "percentOfThresholdPace",
        "structure": [
            {"type": "step", "length": {"unit": "repetition", "value": 1},
             "steps": [step("Warmup", 400, "meter", "warmUp")]},
            {"type": "repetition", "length": {"unit": "repetition", "value": 8},
             "steps": [step("Drill", 50, "meter")]},
            {"type": "repetition", "length": {"unit": "repetition", "value": 6},
             "steps": [step("250 m", 250, "meter"),
                       step("Recovery", 20, "second", "rest")]},
            {"type": "step", "length": {"unit": "repetition", "value": 1},
             "steps": [step("Cooldown", 400, "meter", "coolDown")]},
        ],
    }
    lib = {"distancePlanned": 2700, "totalTimePlanned": 50 / 60,
           "structure": structure}
    plan = {"native_distance_planned_m": 2700,
            "native_duration_planned_h": 50 / 60,
            "native_structure": deepcopy(structure)}
    return lib, plan


def test_swim_transfer_full_match():
    lib, plan = fixture_pair()
    result = check(lib, plan)
    assert result["status"] == "PASS"
    assert result["destination_recovery_seconds"] == 120


def test_swim_transfer_detects_lost_recoveries():
    lib, plan = fixture_pair()
    plan["native_structure"]["structure"][2]["steps"].pop()
    result = check(lib, plan)
    assert result["status"] == "FAIL"
    assert result["checks"]["all_blocks_identical"] is False
    assert result["destination_recovery_seconds"] == 0


def test_swim_transfer_requires_exact_planned_fields():
    lib, plan = fixture_pair()
    plan["native_duration_planned_h"] = None
    assert check(lib, plan)["status"] == "FAIL"
    plan["native_duration_planned_h"] = 50 / 60
    plan["native_distance_planned_m"] = 2500
    assert check(lib, plan)["status"] == "FAIL"


def test_swim_transfer_does_not_accept_summary_only():
    lib, plan = fixture_pair()
    plan.pop("native_structure")
    assert check(lib, plan)["status"] == "FAIL"
