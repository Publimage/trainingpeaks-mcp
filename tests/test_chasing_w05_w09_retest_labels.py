from scripts.ironman_jobs import chasing_w05_w09_retest_labels as x

def test_approved_instances_and_no_spurious_tests():
 assert x.PLAN==685173 and x.PERSON==6682479
 assert [z["id"] for z in x.SPEC]==[4000954221,4000954256,4001048397]
 assert [z["date"] for z in x.SPEC]==["2027-02-03","2027-02-04","2027-03-03"]
