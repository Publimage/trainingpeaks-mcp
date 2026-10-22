"""Offline fixtures using the native Builder shape; no provider connection."""

import copy

from scripts.ironman_jobs.swim_distance_audit import audit_swim_distance


def native_swim():
    # 300 m warm-up + three 100 m efforts with 20 s rest + final 100 m.
    return {
        "primaryLengthMetric": "distance",
        "structure": [
            {"type": "step", "length": {"value": 1, "unit": "repetition"},
             "steps": [{"name": "Warm-up", "length": {"value": 300, "unit": "meter"}}]},
            {"type": "repetition", "length": {"value": 3, "unit": "repetition"},
             "steps": [
                 {"name": "Swim", "length": {"value": 100, "unit": "meter"}},
                 {"name": "Recover", "intensityClass": "rest",
                  "length": {"value": 20, "unit": "second"}},
             ]},
            {"type": "step", "length": {"value": 1, "unit": "repetition"},
             "steps": [{"name": "Swim", "length": {"value": 100, "unit": "meter"}}]},
        ],
    }


def test_correct_distance_is_pass():
    result = audit_swim_distance(700.0, native_swim())
    assert result == {"status": "PASS", "code": "SWIM_DISTANCE_OK",
                      "declared_m": 700, "computed_m": 700, "delta_m": 0}


def test_discrepancy_is_fail_with_explicit_delta():
    result = audit_swim_distance(800, native_swim())
    assert result["status"] == "FAIL"
    assert result["code"] == "SWIM_DISTANCE_MISMATCH"
    assert result["delta_m"] == -100


def test_missing_structure_fails_closed():
    assert audit_swim_distance(700, {})["code"] == "SWIM_DISTANCE_UNVERIFIABLE"


def test_invalid_declared_metres_fails_closed():
    assert audit_swim_distance(None, native_swim())["status"] == "FAIL"
    assert audit_swim_distance(True, native_swim())["status"] == "FAIL"


def test_unrecognized_unit_fails_closed():
    data = native_swim()
    data["structure"][0]["steps"][0]["length"]["unit"] = "yard"
    result = audit_swim_distance(700, data)
    assert result["status"] == "FAIL"
    assert result["reason"] == "STEP_UNIT_UNSUPPORTED"


def test_timed_active_step_fails_closed():
    data = native_swim()
    data["structure"][1]["steps"][1]["intensityClass"] = "active"
    assert audit_swim_distance(700, data)["reason"] == "TIMED_ACTIVE_STEP_UNSUPPORTED"


def test_zero_repetitions_fails_closed():
    data = native_swim()
    data["structure"][1]["length"]["value"] = 0
    assert audit_swim_distance(700, data)["status"] == "FAIL"


def test_does_not_mutate_source():
    data = native_swim()
    original = copy.deepcopy(data)
    audit_swim_distance(700, data)
    assert data == original
