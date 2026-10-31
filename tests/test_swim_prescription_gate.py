from tp_mcp.tools.swim_prescription_gate import (
    audit_swims,assert_swim_ready,SwimPrescriptionGateError)
import pytest

def test_source_library_and_plan_both_require_metres_and_hours():
    lib=[{"workoutTypeId":1,"exerciseLibraryItemId":10,
          "distancePlanned":2500,"totalTimePlanned":55/60}]
    plan=[{"workoutTypeValueId":1,"workoutId":11,
           "distancePlanned":2500.0,"totalTimePlanned":55/60}]
    assert assert_swim_ready(lib,surface="Workout Library")["status"]=="PASS"
    assert assert_swim_ready(plan,surface="Training Plan")["status"]=="PASS"
def test_blank_duration_is_release_blocking_even_with_metres():
    w=[{"workoutTypeId":1,"exerciseLibraryItemId":22,"distancePlanned":3100,
        "totalTimePlanned":None}]
    report=audit_swims(w,surface="library")
    assert report["status"]=="BLOCK_RELEASE"
    assert "NATIVE_PLANNED_DURATION_HOURS_MISSING" in report["defects"][0]["issues"]
    with pytest.raises(SwimPrescriptionGateError):
        assert_swim_ready(w,surface="library")
def test_blank_metres_also_blocks_even_with_duration():
    w=[{"workoutTypeValueId":1,"workoutId":23,"distancePlanned":None,
        "totalTimePlanned":1.0}]
    assert audit_swims(w,surface="plan")["status"]=="BLOCK_RELEASE"
def test_bike_skipped_but_swim_required():
    with pytest.raises(SwimPrescriptionGateError):
        assert_swim_ready([{"workoutTypeId":2,"totalTimePlanned":1}],surface="empty")
