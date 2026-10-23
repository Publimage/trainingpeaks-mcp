from scripts.ironman_jobs import chasing_w01_baseline_tests as x

def test_exact_scope_and_prescriptions():
 assert x.PLAN==685173 and x.OWNER==2116886 and x.PERSON==6682479
 assert x.START=="2027-01-04" and x.END=="2027-01-10"
 assert [v["id"] for v in x.TEMPLATE_MAP]==[4000490168,4000486945,4000490118]
 assert {v["sport"] for v in x.TEMPLATE_MAP}=={1,2,3}
 assert [v["date"] for v in x.TEMPLATE_MAP]==["2027-01-04","2027-01-05","2027-01-07"]
