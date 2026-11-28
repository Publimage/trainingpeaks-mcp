from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/note_attachment_methods_readonly.py"
def test_allow_only_safe_http_methods():
 s=P.read_text();ast.parse(s)
 assert '["OPTIONS","HEAD","GET"]' in s
 assert "method=method" in s and "PROVIDER_WRITES:0" in s
 assert '"POST"' not in s and '"PUT"' not in s and '"DELETE"' not in s
