"""Pure safety tests for one-shot native strength lab library canary."""
from scripts.ironman_jobs.native_strength_library_one_canary import (
    LIB_ID, LIB_NAME, OWNER, TITLE, build_candidate, strict_readback
)

def test_exact_isolated_lab_identity():
    assert LIB_ID == 3890637
    assert LIB_NAME == "[MCP TEST] Integration Lab"
    assert OWNER == 2116886
    assert TITLE.startswith("[MCP TEST]")

def test_payload_preserves_native_blocks_and_type():
    native={"workoutType":"StructuredStrength","instructions":"test","blocks":[
        {"blockType":"SingleExercise","prescriptions":[{"exerciseId":"144","sets":[{"Reps":"8"}]}]}]}
    p=build_candidate(native)
    assert p["exerciseLibraryId"] == LIB_ID
    assert p["exerciseLibraryItemType"] == "StructuredStrength"
    assert p["structure"]["blocks"] == native["blocks"]
    assert strict_readback({**p, "exerciseLibraryItemId": 1})

def test_classic_workout_template_must_fail():
    assert not strict_readback({"exerciseLibraryId":LIB_ID,"itemName":TITLE,
                                "exerciseLibraryItemType":"WorkoutTemplate",
                                "workoutTypeId":9,"structure":{"blocks":[{"prescriptions":[{}]}]}})
    assert not strict_readback({"exerciseLibraryId":LIB_ID,"itemName":TITLE,
                                "exerciseLibraryItemType":"StructuredStrength",
                                "workoutTypeId":9,"structure":None})
