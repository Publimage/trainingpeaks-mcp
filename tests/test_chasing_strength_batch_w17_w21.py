from scripts.ironman_jobs import chasing_strength_batch_w17_w21 as m

def test_scope():
 assert m.PLAN==685173 and m.PERSON==6682479
 assert (m.START_WEEK,m.END_WEEK,m.EXPECTED_BEFORE)==(17,21,271)
