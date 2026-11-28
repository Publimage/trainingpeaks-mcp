from scripts.ironman_jobs import chasing_lab_restore_audit as x

def test_scope():
    assert x.PLAN==684484 and x.OWNER==2116886
