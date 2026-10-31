from scripts.ironman_jobs import chasing_plan_w03_w04 as m
def test_manifest():
 assert m.PLAN==685173 and m.OWNER==2116886
 assert len(m.ITEMS)==19
 assert {w for w,*_ in m.ITEMS}=={3,4}
 assert all(0<=d<=6 and k in m.LIB for _,d,k,_ in m.ITEMS)
 assert len({(w,d,k) for w,d,k,_ in m.ITEMS})==19
