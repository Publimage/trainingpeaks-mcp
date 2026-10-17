from pathlib import Path
P=Path("scripts/ironman_jobs/intermediate_marketplace_html_20261017.py")
def test_contract():
    t=P.read_text()
    assert "PLAN=684602" in t
    assert "INTERMEDIATE_HTML_VERIFIED" in t
    assert "_retry_on_401=False" in t
    assert "isPublic" in t
    assert "price" in t
