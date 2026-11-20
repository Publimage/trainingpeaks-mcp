from scripts.ironman_jobs import chasing_strength_relayout_common_20261022 as m

def test_exact_18_moved_weeks_and_dates():
    assert len(m.CANARY_WEEKS)==1 and m.CANARY_WEEKS==(19,)
    assert len(m.REST_WEEKS)==17
    assert len(m.ALL_MOVE_WEEKS)==18
    assert m.dt(19,1)=="2027-05-11"
    assert m.dt(19,0)=="2027-05-10"
    assert m.dt(17,4)=="2027-04-30"
    assert not ({2,3,4} & m.ALL_MOVE_WEEKS)
    assert m.label(17,"M45","VEN")=="CHASING THE SLOT | W17 VEN | Forza M45"
