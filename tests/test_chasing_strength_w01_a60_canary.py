from scripts.ironman_jobs import chasing_strength_w01_a60_canary as m

def test_scope():
 assert m.PLAN==685173 and m.OWNER==2116886 and m.PERSON==6682479
 assert m.DATE=='2027-01-05'
