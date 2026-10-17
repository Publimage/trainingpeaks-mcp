from scripts.ironman_jobs import chasing_w02_run_to_monday as x
def test_guarded_scope():
    assert x.PLAN==685173 and x.OWNER==2116886
    assert x.SRC=="2027-01-15" and x.DST=="2027-01-11"
    assert x.SPORT==3 and x.EXPECTED_MIN==45
    assert x.protect({"a":1,"workoutDay":"x","lastModifiedDate":"t"})=={"a":1}
