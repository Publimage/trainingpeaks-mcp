from pathlib import Path

def test_block_script():
 s=Path("scripts/ironman_jobs/chasing_strength_rests_plan_w01_w08.py").read_text()
 assert "asyncio.run(run(1,8))" in s
 assert "no duration changes" in s
