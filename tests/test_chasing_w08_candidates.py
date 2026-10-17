from scripts.ironman_jobs import chasing_w08_candidates as m

def test_recovery():
 assert 175 in m.NEEDS['BI'] and 35 in m.NEEDS['RU']
