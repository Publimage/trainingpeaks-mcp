from scripts.ironman_jobs import chasing_guides_release_common_20261022 as g

def test_pdf_small_render_source_is_structurally_valid():
    d=g.Sheet("Smoke Test")
    d.heading("TEST PDF")
    d.paragraph("Documento di prova con testo lungo e ripetuto. " * 10)
    b=g.pdf(d.finish())
    assert b.startswith(b"%PDF-1.4")
    assert b.rstrip().endswith(b"%%EOF")
    assert b"/Type /Catalog" in b
    assert b"xref" in b and b"/Count 1" in b

def test_release_constants():
    assert g.PLAN==685173 and g.PERSON==6682479
    assert len(g.NAMES)==2
    assert set(g.OLD)=={97265,97222}
    assert set(g.KEEP)=={97223}
    assert 9 in g.NOTES and 17 in g.NOTES
