from pathlib import Path

def test_one_time_resume_scope():
 p=Path("scripts/ironman_jobs/chasing_w01_partial_resume.py").read_text()
 assert "PLAN=685173" in p and "OWNER=2116886" in p
 assert "BACKUP.exists()" in p and "PARTIAL_ANCHOR_NOT_JAN05" in p
 assert "2027-01-04" in p and "2027-01-08" in p
