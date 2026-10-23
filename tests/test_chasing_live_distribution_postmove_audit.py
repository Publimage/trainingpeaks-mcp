from scripts.ironman_jobs import chasing_live_distribution_postmove_audit as x

def test_private_scope():
 assert x.PLAN==685173 and x.PERSON==6682479 and x.OWNER==2116886
 assert x.ANCHOR.isoformat()=="2027-01-04"
 assert x.SUNDAY_SHIFT==frozenset({3,7,9,11})

def test_final_overlay_count():
 c=x.canonical_expected()
 assert sum(c.values())==276
 for w in range(1,24):
  assert c[(x.date_for(w,0),"RU")]==1
  assert c[(x.date_for(w,4),"RU")]==0
 for w in x.SUNDAY_SHIFT:
  assert c[(x.date_for(w,6),"RU")]==1
