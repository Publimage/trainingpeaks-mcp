from pathlib import Path
def test_exact_plan_and_only_three_tuesday_swims():
 s=Path("scripts/ironman_jobs/chasing_w01_w04_swim_mwf.py").read_text()
 assert "PLAN=685173" in s and "OWNER=2116886" in s
 assert s.count('"week":')==4 # three moves and one output reference
 assert "4000490220" in s and "4000591453" in s and "4000591594" in s
 assert "W01_test_exception" in s
