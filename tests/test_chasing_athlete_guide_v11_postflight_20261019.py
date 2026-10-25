from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/chasing_athlete_guide_v11_postflight_20261019.py"
def test_readonly_postflight_contract():
    s=P.read_text(); ast.parse(s)
    assert "PLAN=685173" in s and "NOTE=2664007" in s
    assert "97265" in s and "97222" in s and "97223" in s
    assert "provider_writes" in s and '"DELETE"' not in s and '"POST"' not in s and '"PUT"' not in s
