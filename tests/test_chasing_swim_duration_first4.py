from scripts.ironman_jobs import chasing_swim_duration_first4 as m

def test_scope():
 assert m.PLAN==685173 and m.OWNER==2116886
 assert len(m.FIXES)==11 and len({x[0] for x in m.FIXES})==11
 assert len({x[1] for x in m.FIXES})==8
 assert set(x[2] for x in m.FIXES)=={50,55,60}
