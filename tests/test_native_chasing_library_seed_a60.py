"""Pure verified native Chasing Strength library canary contracts."""
from scripts.ironman_jobs.native_chasing_library_seed_a60 import SOURCE_LIB,LAB_LIB,SOURCE_ID,TITLE,copy_payload,is_native
def test_exact_scope():
    assert SOURCE_LIB==3890637 and LAB_LIB==3894341 and SOURCE_ID=="330612"
    assert copy_payload()=={"libraryId":3894341,"workoutLibraryItemId":330612,"title":TITLE}
    assert "W01" not in TITLE and "2027" not in TITLE
def test_native_nine_blocks():
    src={"workout":{"workoutType":"StructuredStrength","blocks":[{"blockType":"WarmUp","prescriptions":[{"sets":[{}]}]}]+[{"blockType":"SingleExercise","prescriptions":[{"sets":[{}]}]}]*8}}
    item={"libraryId":3894341,"title":TITLE,"workoutLibraryItemType":"ActivityWorkoutTemplate",**src}
    assert is_native(item,src)
