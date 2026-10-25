from scripts.ironman_jobs import half_beginner_16w_strength as m
from scripts.ironman_jobs.half_beginner_16w_prod import items
def test_scope_and_native_exercises():
 rows=m.work()
 assert len(rows)==15 and sum(x["minutes"] for x in rows)==sum(x["minutes"] for x in items() if x["sport"]=="ST")
 assert all(x["day"]==2 and x["week"]<=15 for x in rows)
 assert m.PLAN==686994
 for r in rows:
  b=m.blocks(r["week"],r["minutes"])
  assert len(b)>=4
  assert m._validate_blocks(b) is None
  assert "70.3" not in m.title(r["minutes"],r["week"])
  assert "W01" not in m.title(r["minutes"],r["week"])
  assert "inclus" in m.instructions(r["week"],r["minutes"]).lower()
