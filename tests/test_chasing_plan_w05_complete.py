from scripts.ironman_jobs import chasing_plan_w05_complete as m

def test_manifest():
 assert m.PLAN==685173 and m.OWNER==2116886
 assert len(m.ITEMS)==10
 assert {w for w,*_ in m.ITEMS}=={5}
 assert len({(w,d,k) for w,d,k,_ in m.ITEMS})==10
