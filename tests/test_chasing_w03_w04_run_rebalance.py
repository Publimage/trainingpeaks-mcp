from scripts.ironman_jobs import chasing_w03_w04_run_rebalance as x

def test_exact_scope():
    assert x.PLAN==685173 and x.PERSON==6682479
    assert [m["week"] for m in x.MOVES]==[3,3,4]
    assert [(m["source"],m["target"]) for m in x.MOVES]==[
      ("2027-01-22","2027-01-18"),("2027-01-21","2027-01-24"),("2027-01-29","2027-01-25")]
    assert len(set(m["target"] for m in x.MOVES))==3
