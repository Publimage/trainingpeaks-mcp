from scripts.ironman_jobs import chasing_24w_library_audit as m

def test_read_only_scope():
 assert m.OWNER==2116886
 assert m.PLAN==685173
 assert set(m.LIB)=={'SW','BI','RU','ST'}
