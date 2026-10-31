"""Verify the exact native Strength library-to-library copy contract."""
from scripts.ironman_jobs.native_strength_library_copy_lab_canary import (
    SOURCE_LIB,LAB_LIB,SOURCE_ID,copy_payload,is_native,TITLE
)

def test_scope_without_dates_or_athletes():
    p=copy_payload()
    assert p=={"libraryId":3890637,"workoutLibraryItemId":330012,"title":TITLE}
    assert SOURCE_LIB==3891875
    assert LAB_LIB==3890637
    assert SOURCE_ID=="330012"
    assert "date" not in str(p).lower()
    assert "calendar" not in str(p).lower()

def test_native_readback():
    s={"workout":{"workoutType":"StructuredStrength","blocks":[{"prescriptions":[{"sets":[{"Reps":6}]}]}]*6}}
    x={"libraryId":3890637,"title":TITLE,"workoutLibraryItemType":"ActivityWorkoutTemplate",**s}
    assert is_native(x,s)
    assert not is_native({**x,"workoutLibraryItemType":"WorkoutTemplate"},s)
