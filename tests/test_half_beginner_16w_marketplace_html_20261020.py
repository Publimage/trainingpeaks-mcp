"""Static safety contract for the plan-686994 description-only writer."""
import ast
import hashlib
from pathlib import Path

SOURCE = Path("scripts/ironman_jobs/half_beginner_16w_marketplace_html_20261020.py")

def _constants():
    root = ast.parse(SOURCE.read_text(encoding="utf-8"))
    return {target.id: ast.literal_eval(node.value)
            for node in root.body if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name)
            and target.id in {"OWNER","PLAN","TITLE","HTML","NOTE","ATTACHMENTS"}}

def test_plan_scope_and_exact_html():
    c = _constants()
    assert c["OWNER"] == 2116886
    assert c["PLAN"] == 686994
    assert c["NOTE"] == 2672039
    assert c["TITLE"] == "ALBERTO FAZI ENDURANCE | 70.3 | 16 settimane | Beginner | Italiano"
    assert len(c["HTML"].encode("utf-8")) == 5681
    assert hashlib.sha256(c["HTML"].encode("utf-8")).hexdigest() == \
        "3d5deba69c6b2900eb817461cc3add034c8bb2c6966182c5e13fa3e7fcdb0900"
    assert c["HTML"].startswith('<div style="max-width:900px;')
    assert c["HTML"].endswith("</div>\n")
    assert "133 allenamenti" in c["HTML"]
    assert "16 note educative settimanali" in c["HTML"]
    assert "self-guided" in c["HTML"]
    assert c["ATTACHMENTS"] == {
        "70_3_Beginner_16W_Guida_Atleta_DEFINITIVA.pdf": (97606,383566),
        "70_3_Beginner_16W_Scheda_Gara_e_Alimentazione_v0_1.pdf": (97607,322297),
    }

def test_scope_and_readback_guards():
    s = SOURCE.read_text(encoding="utf-8")
    assert 'p.get("isPublic") is False' in s
    assert 'p.get("workoutCount") == 133' in s
    assert 'p.get("description") in (None, "", HTML)' in s
    assert '"PUT", f"/plans/v1/plans/{PLAN}"' in s
    assert '"description": HTML' in s
    assert '_retry_on_401=False' in s
    assert 'p2.get("description") != HTML' in s
    assert 'NOTES_PDFS_CHANGED' in s
    assert 'PLAN_SCOPE_DRIFT' in s
