"""Independent synthetic expectations; no private payloads or provider writes."""
import copy
import json

import pytest

from scripts.ironman_jobs.swim_audit_report import (
    SNAPSHOT_SCHEMA, PRESCRIPTION_SCHEMA, audit_swim_report, payload_sha256,
)

REVISION = "a" * 40


def inputs(coverage="complete", with_rest=True):
    target = {"provider": "trainingpeaks", "owner_id": "synthetic-owner",
              "resource_kind": "library_template", "container_id": "synthetic-library",
              "workout_id": "synthetic-workout"}
    source = {"source_id": "synthetic-source", "revision": "v1", "section": "swim-1"}
    steps = [{"length": {"value": 100, "unit": "meter"}}]
    if with_rest:
        steps.append({"length": {"value": 20, "unit": "second"},
                      "intensityClass": "rest", "targets": [{"minValue": 0, "maxValue": 0}]})
    steps.append({"length": {"value": 100, "unit": "meter"}})
    snapshot = {"schema": SNAPSHOT_SCHEMA, "target": copy.deepcopy(target),
                "distance_planned": 200, "structure": {
                    "primaryLengthMetric": "distance", "structure": [
                        {"type": "step", "length": {"value": 1, "unit": "repetition"},
                         "steps": steps}]}}
    prescription = {"schema": PRESCRIPTION_SCHEMA, "target": copy.deepcopy(target),
                    "source": copy.deepcopy(source), "snapshot_sha256": payload_sha256(snapshot),
                    "recovery": {"schema": "IRONMAN_SWIM_RECOVERY_V1", "source_ref": "synthetic-source",
                                 "coverage": coverage, "total_m": 200,
                                 "pauses": [{"after_m": 100, "seconds": 20}]}}
    request = {"expected_target": target, "expected_source": source,
               "expected_prescription_sha256": payload_sha256(prescription),
               "validator_revision": REVISION}
    return snapshot, prescription, request


def evaluate(data):
    snapshot, prescription, request = data
    return audit_swim_report(snapshot, prescription, **request)


def rebind_for_test(data):
    # Only a fixture helper. Production must obtain a new reviewed manifest;
    # it MUST NOT automatically refresh these references to make an error pass.
    snapshot, prescription, request = data
    prescription["snapshot_sha256"] = payload_sha256(snapshot)
    request["expected_prescription_sha256"] = payload_sha256(prescription)


def test_complete_match_has_scoped_pass_but_never_publishing_permission():
    report = evaluate(inputs())
    assert report["status"] == "PASS" and report["technical_checks_passed"] is True
    assert report["publishing_authorized"] is False
    assert report["external_authenticity_verified"] is False
    assert "physiological_quality" in report["not_checked"]
    assert report["checks"]["recoveries"]["actual_rest_seconds"] == 20


def test_missing_recovery_is_not_hidden_by_correct_metres():
    report = evaluate(inputs(with_rest=False))
    assert report["status"] == "FAIL"
    assert report["checks"]["distance"]["status"] == "PASS"
    assert report["checks"]["recoveries"]["missing_pauses"] == [{"after_m": 100, "seconds": 20}]


def test_targeted_success_stays_partial():
    report = evaluate(inputs(coverage="targeted"))
    assert report["status"] == "PARTIAL" and report["technical_checks_passed"] is False


@pytest.mark.parametrize("field,value", [
    ("owner_id", "other-owner"), ("resource_kind", "training_plan_workout"),
    ("container_id", "other-container"), ("workout_id", "other-workout"),
])
def test_wrong_snapshot_identity_is_blocked_before_checks(field, value):
    data = inputs()
    data[0]["target"][field] = value
    report = evaluate(data)
    assert report["status"] == "UNVERIFIABLE"
    assert report["checks"]["binding"]["code"] == "SNAPSHOT_TARGET_MISMATCH"
    assert report["checks"]["distance"]["status"] == "NOT_RUN"


def test_prescription_for_other_workout_is_blocked():
    data = inputs()
    data[1]["target"]["workout_id"] = "other"
    assert evaluate(data)["checks"]["binding"]["code"] == "PRESCRIPTION_TARGET_MISMATCH"


@pytest.mark.parametrize("field", ["source_id", "revision", "section"])
def test_changed_source_is_blocked_even_when_training_numbers_match(field):
    data = inputs()
    data[2]["expected_source"][field] = "new-value"
    assert evaluate(data)["checks"]["binding"]["code"] == "SOURCE_VERSION_MISMATCH"


def test_builder_change_invalidates_old_snapshot_binding():
    data = inputs()
    data[0]["structure"]["structure"][0]["steps"][1]["length"]["value"] = 30
    assert evaluate(data)["checks"]["binding"]["code"] == "SNAPSHOT_CHANGED"


def test_prescription_change_cannot_reuse_reviewed_digest():
    data = inputs()
    data[1]["recovery"]["pauses"][0]["seconds"] = 30
    assert evaluate(data)["checks"]["binding"]["code"] == "PRESCRIPTION_CHANGED"


def test_recovery_source_reference_is_checked():
    data = inputs()
    data[1]["recovery"]["source_ref"] = "unrelated-source"
    assert evaluate(data)["checks"]["binding"]["code"] == "RECOVERY_SOURCE_MISMATCH"


def test_new_snapshot_needs_both_new_snapshot_pin_and_new_reviewed_digest():
    data = inputs()
    data[0]["distance_planned"] = 300
    data[1]["snapshot_sha256"] = payload_sha256(data[0])
    assert evaluate(data)["checks"]["binding"]["code"] == "PRESCRIPTION_CHANGED"


@pytest.mark.parametrize("field", ["schema", "target", "source", "snapshot_sha256", "recovery"])
def test_missing_envelope_fields_never_pass(field):
    data = inputs()
    del data[1][field]
    assert evaluate(data)["status"] == "UNVERIFIABLE"


@pytest.mark.parametrize("value", [None, "", "v1", "A" * 40, True])
def test_validator_revision_must_be_explicit_sha(value):
    data = inputs()
    data[2]["validator_revision"] = value
    assert evaluate(data)["checks"]["binding"]["code"] == "VALIDATOR_REVISION_REQUIRED"


@pytest.mark.parametrize("value", [None, "", "a" * 63, True])
def test_missing_or_malformed_review_digest_never_passes(value):
    data = inputs()
    data[2]["expected_prescription_sha256"] = value
    assert evaluate(data)["status"] == "UNVERIFIABLE"


def test_unsupported_native_unit_is_inconclusive_not_a_numeric_mismatch():
    data = inputs()
    data[0]["structure"]["structure"][0]["steps"][0]["length"]["unit"] = "yard"
    rebind_for_test(data)
    report = evaluate(data)
    assert report["status"] == "UNVERIFIABLE"
    assert report["checks"]["distance"]["status"] == "UNVERIFIABLE"


def test_real_distance_failure_remains_visible_with_unknown_recovery_coverage():
    data = inputs()
    data[0]["distance_planned"] = 300
    data[1]["recovery"]["coverage"] = "unknown"
    rebind_for_test(data)
    report = evaluate(data)
    assert report["status"] == "FAIL"
    assert report["checks"]["distance"]["delta_m"] == -100
    assert report["checks"]["recoveries"]["status"] == "UNVERIFIABLE"


def test_wrong_pause_position_same_seconds_fails():
    data = inputs()
    data[1]["recovery"]["pauses"][0]["after_m"] = 200
    rebind_for_test(data)
    assert evaluate(data)["status"] == "FAIL"


def test_complete_no_pause_prescription_can_pass_for_no_pause_workout():
    data = inputs(with_rest=False)
    data[1]["recovery"]["pauses"] = []
    rebind_for_test(data)
    assert evaluate(data)["status"] == "PASS"


def test_additional_pause_fails_for_complete_no_pause_prescription():
    data = inputs()
    data[1]["recovery"]["pauses"] = []
    rebind_for_test(data)
    assert evaluate(data)["status"] == "FAIL"


def test_missing_structure_is_unverifiable():
    data = inputs()
    data[0]["structure"] = None
    rebind_for_test(data)
    assert evaluate(data)["status"] == "UNVERIFIABLE"


def test_non_json_input_is_reported_without_dumping_payload():
    data = inputs()
    data[0]["distance_planned"] = float("nan")
    report = evaluate(data)
    assert report["checks"]["binding"]["code"] == "NON_JSON_INPUT"
    assert "target" not in report


def test_wrong_expected_target_shape_rejects_boolean_identifier():
    data = inputs()
    data[2]["expected_target"]["workout_id"] = True
    assert evaluate(data)["checks"]["binding"]["code"] == "TARGET_VALUES"


def test_same_inputs_produce_identical_serializable_report():
    data = inputs()
    first = evaluate(data)
    assert first == evaluate(data)
    assert json.loads(json.dumps(first, allow_nan=False)) == first


def test_no_input_mutation_or_returned_aliases():
    data = inputs()
    original = copy.deepcopy(data)
    report = evaluate(data)
    assert data == original
    report["target"]["workout_id"] = "edited-report"
    report["source"]["revision"] = "edited-report"
    assert data == original


def test_dictionary_key_order_does_not_change_hash():
    assert payload_sha256({"a": 1, "b": 2}) == payload_sha256({"b": 2, "a": 1})
