from scripts.ironman_jobs import chasing_strength_batch_w01_w08 as m

def test_scope():
 assert m.PLAN==685173 and m.PERSON==6682479
 assert (m.START_WEEK,m.END_WEEK,m.EXPECTED_BEFORE)==(1,8,250)
