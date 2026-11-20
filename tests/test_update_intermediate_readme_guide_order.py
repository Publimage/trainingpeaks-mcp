from pathlib import Path
import ast
S=Path(__file__).resolve().parents[1]/"scripts/ironman_jobs/update_intermediate_readme_guide_order.py"
def test_body_only_plan_scoped():
 t=S.read_text();ast.parse(t)
 assert "PLAN=684602" in t and "NOTE=2653899" in t
 assert "OWNER=2116886" in t
 assert "README_FIRST_GUIDE_ORDER_UPDATED_VERIFIED" in t
 assert "ANOTHER_NOTE_MODIFIED" in t and "README_PDF_ATTACHMENTS_CHANGED" in t
 assert "PDFS=" in t and "95228" in t and "95193" in t and "95194" in t
 assert '"DELETE"' not in t and '"POST"' not in t
 assert t.count("_retry_on_401=False")==1
