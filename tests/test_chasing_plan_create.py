from scripts.ironman_jobs import chasing_plan_create as p
def test_scope():
 assert p.OWNER==2116886
 assert p.TITLE.endswith("| BOZZA")
 assert p.LIB==3891872 and p.ITEM==14962927
 assert p.ANCHOR=="2027-01-04" and p.FIRST=="2027-01-05"
 assert "nessuna forza" in p.DESCRIPTION.lower()
