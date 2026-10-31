from scripts.ironman_jobs import chasing_plan_w06_complete as m

def test_scope():
 assert m.OWNER==2116886 and m.PLAN==685173
 assert len(m.ITEMS)==10
 assert {w for w,*_ in m.ITEMS}=={6}
 assert len({(w,d,k) for w,d,k,_ in m.ITEMS})==10
