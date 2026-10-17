from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/intermediate_release_postflight.py"
def test_readonly_guards():
 s=P.read_text();ast.parse(s)
 assert "OWNER=2116886" in s and "PLAN=684602" in s
 assert "95228" in s and "95193" in s and "95194" in s
 assert "len(r.data)==35" in s and "259" in s and "24" in s
 assert "temp_signed_note_removed" in s
 assert '"PUT"' not in s and '"POST"' not in s and '"DELETE"' not in s
