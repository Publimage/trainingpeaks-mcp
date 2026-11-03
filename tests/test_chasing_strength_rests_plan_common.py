from pathlib import Path

def test_scoped_script():
 src=Path("scripts/ironman_jobs/chasing_strength_rests_plan_common.py").read_text()
 assert "PLAN=685173" in src and "PERSON=6682479" in src
 assert 'EXT={"D45":"D40","M35":"M30","M40":"M45"}' in src
 assert "no_duration_changes" in src and "no_athlete_calendar" in src
