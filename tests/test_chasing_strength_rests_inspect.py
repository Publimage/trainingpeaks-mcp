from pathlib import Path

def test_safe_readonly_inspection():
 text=Path("scripts/ironman_jobs/chasing_strength_rests_inspect.py").read_text()
 assert "LIB=3894341" in text and "OWNER=2116886" in text
 assert "h.post(" not in text and "h.put(" not in text
