from pathlib import Path

def test_read_only_exact_scope():
 code=Path("scripts/ironman_jobs/chasing_strength_rests_global_audit.py").read_text()
 assert "PLAN=685173;PERSON=6682479;LIB=3894341" in code
 assert "27" in code and "get(" in code
 assert "h.post(" not in code and "h.put(" not in code
