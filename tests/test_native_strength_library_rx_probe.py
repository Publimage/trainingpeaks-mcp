from scripts.ironman_jobs.native_strength_library_rx_probe import endpoint,shape,LIBS

def test_explicit_libraries_only():
    assert endpoint(3890637).endswith("/3890637")
    assert LIBS[3891875]=="ALBERTO FAZI ENDURANCE | Forza | IT"

def test_shape_exposes_native_metadata():
    a=shape([{"id":45,"title":"canary","workoutLibraryItemType":"ActivityWorkoutTemplate","workout":{"blocks":[]}}])
    assert a["shape"]=="list"
    assert a["samples"][0]["type"]=="ActivityWorkoutTemplate"
