from scripts.ironman_jobs import chasing_w01_reanchor as x

def test_exact_scope():
 assert x.PLAN==685173 and x.OWNER==2116886
 assert x.SRC=="2027-01-08" and x.DST=="2027-01-04"
 assert x.stable({"a":2,"lastModifiedDate":"x","workoutDay":"y"})=={"a":2}
