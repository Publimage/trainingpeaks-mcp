def test_strict_lab_only():
 from scripts.ironman_jobs import chasing_strength_rest_lab_canary as x
 assert x.LIB==3890637 and x.ID=="330612" and x.OWNER==2116886
 assert x.LIB!=3894341
