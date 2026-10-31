from scripts.ironman_jobs import chasing_monday_distribution_common as x

def test_scope():
 assert x.OWNER==2116886 and x.PERSON==6682479 and x.PLAN==685173
 assert (13,16) in {(5,8),(9,12),(13,16),(17,20),(21,23)}
 assert x.ANCHOR.isoformat()=="2027-01-04"
 assert x.SUNDAY_WEeks==frozenset({7,9,11})
