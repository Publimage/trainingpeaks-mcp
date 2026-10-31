from pathlib import Path

def test_week_scope():
 source=Path("scripts/ironman_jobs/chasing_intermediate_layout_w04.py").read_text()
 assert "asyncio.run(run(4))" in source
 common=Path("scripts/ironman_jobs/chasing_w01_w04_intermediate_layout_common.py").read_text()
 assert "PLAN=685173" in common and "OWNER=2116886" in common
 assert "library_writes" in common and "private" in common
