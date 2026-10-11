from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/pdf_note_inventory_readonly.py"
def test_readonly(): 
 s=S.read_text();ast.parse(s)
 assert "2655001" in s and "2653899" in s
 assert '"POST"' not in s and '"PUT"' not in s and '"DELETE"' not in s
