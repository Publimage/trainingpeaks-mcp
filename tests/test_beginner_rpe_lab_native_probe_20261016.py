from pathlib import Path
def test_scope_and_readonly():
 s=Path("scripts/ironman_jobs/beginner_rpe_lab_native_probe_20261016.py").read_text()
 assert "P=684206;WID=3994992835" in s
 assert "isPublic" in s and "False" in s
 assert "client.put(" not in s
 for t in ("._request(",".put(", ".post(", ".delete(", ".patch("):assert t not in s
