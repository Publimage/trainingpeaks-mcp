from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/note_put_pdf_canary_readback.py"
def test_readonly(): 
 s=S.read_text();ast.parse(s)
 assert "2655235" in s and "684484" in s
 assert '"DELETE"' not in s and '"PUT"' not in s and '"POST"' not in s
