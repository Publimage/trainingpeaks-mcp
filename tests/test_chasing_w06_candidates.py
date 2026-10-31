from scripts.ironman_jobs import chasing_w06_candidates as m

def test_scope():
 assert set(m.LIB)=={'SW','BI','RU'}
 assert 255 in m.NEEDS['BI']
