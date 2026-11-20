from scripts.ironman_jobs import chasing_plan_w01_w02 as m
def test_manifest():
 assert m.PLAN==685173 and m.OWNER==2116886
 assert len(m.ITEMS)==20
 assert len(set((w,d,s) for w,d,s,_ in m.ITEMS))==20
 assert all(s in m.LIB and w in (1,2) and 0<=d<=6 for w,d,s,_ in m.ITEMS)
 assert set(x[2] for x in m.ITEMS)=={"SW","BI","RU"}
