"""Synthetic fixtures only. Never includes private provider payloads."""
import copy
import pytest
from scripts.ironman_jobs.swim_recovery_audit import audit_swim_recoveries, SCHEMA


def swim(m):
    return {"length": {"value": m, "unit": "meter"}, "openDuration": False}


def rest(s):
    return {"name": "Recover", "length": {"value": s, "unit": "second"},
            "intensityClass": "rest", "targets": [{"minValue": 0, "maxValue": 0}]}


def block(n, *steps):
    return {"type": "step" if n == 1 else "repetition",
            "length": {"value": n, "unit": "repetition"}, "steps": list(steps)}


def native(*blocks):
    return {"primaryLengthMetric": "distance", "structure": list(blocks)}


def spec(total=400, pauses=None, coverage="complete"):
    if pauses is None:
        pauses = [(100, 20), (200, 20), (300, 20)]
    return {"schema": SCHEMA, "source_ref": "synthetic:independent-prescription-v1",
            "coverage": coverage, "total_m": total,
            "pauses": [{"after_m": p, "seconds": s} for p, s in pauses]}


def good():
    return native(block(3, swim(100), rest(20)), block(1, swim(100)))


def test_n_minus_one_is_verified_when_explicitly_prescribed():
    r = audit_swim_recoveries(spec(), good())
    assert r["status"] == "PASS" and r["actual_rest_seconds"] == 60


def test_n_recoveries_also_pass_when_explicitly_prescribed():
    assert audit_swim_recoveries(spec(pauses=[(100,20),(200,20),(300,20),(400,20)]),
                                native(block(4, swim(100), rest(20))))["status"] == "PASS"


def test_missing_rests_do_not_pass_even_when_metres_match():
    r = audit_swim_recoveries(spec(), native(block(4, swim(100))))
    assert r["status"] == "FAIL" and len(r["missing_pauses"]) == 3


def test_wrong_duration_is_detected():
    assert audit_swim_recoveries(spec(), native(block(3, swim(100), rest(10)), block(1, swim(100))))["status"] == "FAIL"


def test_same_total_rest_time_at_wrong_position_fails():
    r = audit_swim_recoveries(spec(pauses=[(100,60)]), native(block(1, swim(200), rest(60), swim(200))))
    assert r["status"] == "FAIL" and r["expected_rest_seconds"] == r["actual_rest_seconds"]


def test_unprescribed_trailing_recovery_is_detected():
    assert audit_swim_recoveries(spec(), native(block(4, swim(100), rest(20))))["status"] == "FAIL"


def test_no_stop_with_no_pauses_passes():
    assert audit_swim_recoveries(spec(pauses=[]), native(block(1, swim(400))))["status"] == "PASS"


def test_pause_in_no_stop_fails():
    assert audit_swim_recoveries(spec(pauses=[]), good())["status"] == "FAIL"


def test_rest_label_on_metres_is_not_stationary_recovery():
    step = swim(400); step["intensityClass"] = "rest"; step["name"] = "5 minutes rest"
    assert audit_swim_recoveries(spec(pauses=[(400,300)]), native(block(1, step)))["status"] == "FAIL"


def test_name_does_not_control_native_recovery_detection():
    data = good(); data["structure"][0]["steps"][1]["name"] = "Pausa"
    assert audit_swim_recoveries(spec(), data)["status"] == "PASS"


@pytest.mark.parametrize("targets", [None, [], [{"minValue":1,"maxValue":1}],
                                    [{"minValue":False,"maxValue":False}]])
def test_invalid_stationary_target_fails(targets):
    data = good(); data["structure"][0]["steps"][1]["targets"] = targets
    assert audit_swim_recoveries(spec(), data)["code"] == "SWIM_RECOVERY_TARGET_INVALID"


def test_targeted_match_is_not_a_complete_pass():
    assert audit_swim_recoveries(spec(pauses=[(200,20)], coverage="targeted"), good())["status"] == "PARTIAL"


def test_missing_targeted_pause_is_a_failure():
    assert audit_swim_recoveries(spec(pauses=[(200,300)], coverage="targeted"), good())["status"] == "FAIL"


def test_consecutive_pause_order_is_not_just_a_sum():
    data = native(block(1, swim(200), rest(20), rest(40), swim(200)))
    r = audit_swim_recoveries(spec(pauses=[(200,40),(200,20)]), data)
    assert r["status"] == "FAIL" and not r["missing_pauses"] and not r["sequence_matches"]


def test_targeted_duplicate_cannot_reuse_one_observed_pause():
    assert audit_swim_recoveries(spec(pauses=[(200,20),(200,20)], coverage="targeted"), good())["status"] == "FAIL"


@pytest.mark.parametrize("bad", [None, {}, {"schema":SCHEMA}])
def test_missing_prescription_blocks_validation(bad):
    assert audit_swim_recoveries(bad, good())["status"] == "UNVERIFIABLE"


@pytest.mark.parametrize("value", [None, True, 0, -1, float("nan"), float("inf"), "20", [15,30]])
def test_ambiguous_or_invalid_seconds_never_pass(value):
    data = spec(); data["pauses"][0]["seconds"] = value
    assert audit_swim_recoveries(data, good())["status"] == "UNVERIFIABLE"


def test_empty_source_is_not_accepted():
    data=spec(); data["source_ref"]=" "
    assert audit_swim_recoveries(data, good())["status"] == "UNVERIFIABLE"


def test_empty_targeted_spec_does_not_create_vacuous_pass():
    assert audit_swim_recoveries(spec(pauses=[], coverage="targeted"), good())["status"] == "UNVERIFIABLE"


def test_metre_mismatch_blocks_recovery_pass():
    assert audit_swim_recoveries(spec(total=500), good())["code"] == "SWIM_RECOVERY_DISTANCE_MISMATCH"


def test_unhandled_nested_blocks_are_not_ignored():
    assert audit_swim_recoveries(spec(), native(block(1, block(4, swim(100)))))["status"] == "UNVERIFIABLE"


def test_timed_active_swimming_is_not_called_stationary_rest():
    data=good(); data["structure"][0]["steps"][1]["intensityClass"]="active"
    assert audit_swim_recoveries(spec(), data)["status"] == "UNVERIFIABLE"


def test_expansion_is_bounded():
    data=native(block(10**6, swim(100), rest(20)))
    assert audit_swim_recoveries(spec(total=10**8, pauses=[]), data)["reason"] == "EXPANDED_STEP_LIMIT"


def test_inputs_are_preserved_and_output_repeatable():
    p, d=spec(), good(); saved=copy.deepcopy((p,d))
    a=audit_swim_recoveries(p,d); b=audit_swim_recoveries(p,d)
    assert a==b and (p,d)==saved


def test_pause_after_workout_end_is_invalid_prescription():
    assert audit_swim_recoveries(spec(pauses=[(500,20)]), good())["status"] == "UNVERIFIABLE"


def test_pause_before_start_and_after_finish_can_be_explicit():
    p=spec(pauses=[(0,30),(400,30)]); d=native(block(1,rest(30),swim(400),rest(30)))
    assert audit_swim_recoveries(p,d)["status"] == "PASS"
