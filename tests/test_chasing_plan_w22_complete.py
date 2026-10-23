from scripts.ironman_jobs import chasing_plan_w22_complete as m

def test_manifest():
 assert m.OWNER==2116886 and m.PLAN==685173
 assert len(m.ITEMS)==12 and {w for w,*_ in m.ITEMS}=={22}
 assert len({(w,d,k) for w,d,k,_ in m.ITEMS})==12
