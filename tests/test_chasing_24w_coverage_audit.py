from scripts.ironman_jobs import chasing_24w_coverage_audit as m

def test_scope():
 assert m.OWNER==2116886 and m.PLAN==685173
 assert set(m.LIB)=={'SW','BI','RU'}
