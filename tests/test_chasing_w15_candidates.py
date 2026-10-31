from scripts.ironman_jobs import chasing_w15_candidates as m

def test_needs():
 assert 300 in m.NEEDS['BI']
