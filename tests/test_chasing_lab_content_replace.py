from scripts.ironman_jobs import chasing_lab_content_replace as m

def test_sacrificial_only():
 assert m.PLAN==684206 and m.RUN_ID==3994993213
 assert m.TEMPLATE_ID==14947461 and m.OWNER==2116886
 assert m.PLAN!=685173
