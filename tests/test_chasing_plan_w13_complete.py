from scripts.ironman_jobs import chasing_plan_w13_complete as m

def test_manifest():
 assert m.OWNER==2116886 and m.PLAN==685173
 assert len(m.ITEMS)==10 and {w for w,*_ in m.ITEMS}=={13}
 assert len({(w,d,k) for w,d,k,_ in m.ITEMS})==10
