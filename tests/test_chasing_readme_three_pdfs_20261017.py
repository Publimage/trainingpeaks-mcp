from pathlib import Path
import ast
P=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/chasing_readme_three_pdfs_20261017.py"
def test_exact_scope_and_safe_resume():
    s=P.read_text(); ast.parse(s)
    assert "PLAN=685173" in s and "NOTE=2664007" in s and "OWNER=2116886" in s
    assert "START | Come usare Chasing the Slot" in s
    assert "CHASING_THE_SLOT_24W_Guida_Atleta_v1.0.pdf" in s
    assert "CHASING_THE_SLOT_24W_Guida_Settimana_per_Settimana_v1.0.pdf" in s
    assert "CHASING_THE_SLOT_24W_Guida_Fueling_Nutrizione_v1.0.pdf" in s
    assert "309ff614cf5f05ba51b8c835b45c9a2ccdfe4b413df4ca028160cf94b5c15150" in s
    assert "ddec8ea8a8390d80a8bc6183b57634dde0eac07091efb42422444be45efb24cb" in s
    assert "598e39ccc5bb311a950ce4cb1c3aefa332246266c9f1c12f7a7b4117ad8d5cb0" in s
    assert 'c._client.request("POST"' in s
    assert '"DELETE"' not in s and '"PUT"' not in s
    assert "if name in amap" in s and "AMBIGUOUS_POST_NO_READBACK_STOP" in s
    assert "other_30_notes_unchanged" in s and "start_note_body_unchanged" in s
