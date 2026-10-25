from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/delete_pdf_transfer_note_lab.py"
def test_only_transport_note():
 s=S.read_text();ast.parse(s)
 assert "LAB=684484" in s and "NOTE=2655001" in s and "OWNER=2116886" in s
 assert '"DELETE"' in s and '"POST"' not in s and '"PUT"' not in s
 assert "TEMP_SIGNED_URL_NOTE_REMOVED_VERIFIED" in s
