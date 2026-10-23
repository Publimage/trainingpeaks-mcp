from scripts.ironman_jobs import chasing_lab_plan_anchor_probe as x

def test_sacrificial_scope():
 assert x.PLAN==684484 and x.OLD=="2027-07-05" and x.NEW=="2027-07-04"
 assert x.PLAN!=685173
