from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/note_attachment_delete_lab_20261019.py"
def test_lab_attachment_delete_scope():
    s=P.read_text(); ast.parse(s)
    assert "LAB=684484" in s and "OWNER=2116886" in s
    assert "ATTACHMENT DELETE CANARY" in s
    assert '/attachments/{aid}' in s
    assert '"DELETE"' in s and '"POST"' in s
    assert "LAB_NOT_RESTORED" in s
    assert "ATTACHMENT_DELETE_ROUTE_VERIFIED" in s
