"""Synthetic edge cases only: no private workout contents or provider access."""

import copy
import pytest

from scripts.ironman_jobs.swim_distance_audit import audit_swim_distance


def sample():
    return {'primaryLengthMetric': 'distance', 'structure': [
        {'type': 'repetition', 'length': {'value': 3, 'unit': 'repetition'},
         'steps': [
             {'length': {'value': 100, 'unit': 'meter'}, 'openDuration': False},
             {'length': {'value': 20, 'unit': 'second'}, 'intensityClass': 'rest'},
             {'length': {'value': 50, 'unit': 'meter'}, 'intensityClass': 'rest'}]}]}


@pytest.mark.parametrize('value', [0, -1, 1.5, True, False, None, '450', float('nan'), float('inf'), -float('inf')])
def test_invalid_declared_distance_never_passes(value):
    result = audit_swim_distance(value, sample())
    assert result['status'] == 'FAIL'
    assert result['code'] == 'SWIM_DISTANCE_UNVERIFIABLE'


def test_multiple_distance_steps_include_easy_swim_but_not_seconds():
    result = audit_swim_distance(450, sample())
    assert result['status'] == 'PASS' and result['computed_m'] == 450


def test_huge_integer_is_exact_and_does_not_crash():
    declared = 10**400
    result = audit_swim_distance(declared, sample())
    assert result['code'] == 'SWIM_DISTANCE_MISMATCH'
    assert result['delta_m'] == 450 - declared


def test_integer_above_float_precision_boundary_is_not_rounded():
    declared = 2**53 + 1
    result = audit_swim_distance(declared, sample())
    assert result['declared_m'] == declared


@pytest.mark.parametrize('flag', ['false', 1, None])
def test_malformed_open_duration_flag_is_unverifiable(flag):
    data = sample()
    data['structure'][0]['steps'][0]['openDuration'] = flag
    assert audit_swim_distance(450, data)['reason'] == 'OPEN_DURATION_FLAG_INVALID'


def test_open_duration_is_unverifiable():
    data = sample()
    data['structure'][0]['steps'][0]['openDuration'] = True
    assert audit_swim_distance(450, data)['reason'] == 'OPEN_DURATION_UNSUPPORTED'


def test_rest_only_workout_cannot_pass():
    data = sample()
    data['structure'][0]['steps'] = [data['structure'][0]['steps'][1]]
    assert audit_swim_distance(450, data)['reason'] == 'NO_SWIM_METRES'


def test_unhandled_nested_repeat_is_not_silently_flattened():
    data = sample()
    data['structure'][0]['steps'] = [copy.deepcopy(data['structure'][0])]
    assert audit_swim_distance(450, data)['code'] == 'SWIM_DISTANCE_UNVERIFIABLE'


def test_recovery_completeness_is_explicitly_outside_distance_scope():
    data = sample()
    data['structure'][0]['steps'].pop(1)
    # This deliberately stays PASS: recovery validation is a separate gate.
    assert audit_swim_distance(450, data)['code'] == 'SWIM_DISTANCE_OK'


def test_changed_local_distance_is_detected_without_mutating_input():
    data = sample()
    original = copy.deepcopy(data)
    result = audit_swim_distance(550, data)
    assert result['code'] == 'SWIM_DISTANCE_MISMATCH' and result['delta_m'] == -100
    assert data == original
