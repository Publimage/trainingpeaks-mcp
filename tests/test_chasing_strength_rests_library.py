from scripts.ironman_jobs import chasing_strength_rests_library as x

def test_exclusive_native_library():
 assert x.LIB==3894341 and x.OWNER==2116886
 assert len(x.ORDER)==7 and set(x.ORDER)==set(x.LIB_ID)
