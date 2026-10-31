from scripts.ironman_jobs import chasing_lab_date_move_canary as x

def test_only_disposable_scope():
    assert x.PLAN==684484 and x.ID==3995256662
    assert x.OLD=="2027-07-06" and x.NEW=="2027-07-07"
    assert x.OWNER==2116886 and x.PLAN!=685173

def test_provider_field_helper():
    assert x.day({"workoutDay":"2027-07-06T00:00:00"})==x.OLD
    assert x.digest({"a":1,"b":2})==x.digest({"b":2,"a":1})
