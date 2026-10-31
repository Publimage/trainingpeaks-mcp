from scripts.ironman_jobs import chasing_strength_rest_planlab_canary as x

def test_scope_lab_only():
 assert x.OWNER==2116886 and x.PLAN==684543 and x.PERSON==6678164
 assert x.PLAN!=685173
