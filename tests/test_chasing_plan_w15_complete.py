from scripts.ironman_jobs import chasing_plan_w15_complete as m

def test_manifest():
 assert m.OWNER==2116886 and m.PLAN==685173
 assert len(m.ITEMS)==11 and {w for w,*_ in m.ITEMS}=={15}
 assert len({(w,d,k) for w,d,k,_ in m.ITEMS})==11
