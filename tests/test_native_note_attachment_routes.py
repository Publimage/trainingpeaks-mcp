from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/native_note_attachment_routes.py"
def test_read_only():
 s=S.read_text();ast.parse(s)
 assert "PLAN=684602" in s and "OWNER=2116886" in s
 assert '"POST"' not in s and '"PUT"' not in s and '"DELETE"' not in s
 assert "PROVIDER_WRITES:0" in s and "len(n.data)==35" in s
