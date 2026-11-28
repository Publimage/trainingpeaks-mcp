from scripts.ironman_jobs import chasing_w05_candidate_audit as m

def test_scope():
 assert m.OWNER==2116886 and m.PLAN==685173
 assert len(m.DAYS)==10
