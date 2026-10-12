from scripts.ironman_jobs import chasing_swim_duration_distance_gate as x
def test_read_only_scope():
 assert x.OWNER==2116886 and x.PLAN==685173 and x.LIB==3891872
 assert x.at(0)=="2027-01-04" and x.at(167)=="2027-06-20"
