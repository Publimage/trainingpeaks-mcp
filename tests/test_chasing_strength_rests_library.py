from pathlib import Path
from scripts.ironman_jobs.chasing_strength_rests_common import LIB_ID

def test_exclusive_native_library():
 code=Path("scripts/ironman_jobs/chasing_strength_rests_library.py").read_text()
 assert "OWNER=2116886; LIB=3894341" in code
 assert "from chasing_strength_rests_common import" in code
 assert len(LIB_ID)==7
