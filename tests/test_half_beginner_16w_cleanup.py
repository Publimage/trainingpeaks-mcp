from scripts.ironman_jobs import half_beginner_16w_cleanup as m
def test_rounding_and_week11_example():
 assert m.minute(34)==35 and m.minute(88)==90 and m.minute(97)==95
 x=m.fixstructure(2,90,"Aerobico | Bici controllo e cadenza 88' · controllo RPE3-4")
 assert [b["steps"][0]["length"]["value"]//60 for b in x["structure"]]==[15,45,25,5]
 y=m.fixstructure(3,35,"Aerobico | Corsa conversazionale 34'")
 assert sum(b["steps"][0]["length"]["value"] for b in y["structure"])==35*60
 assert m.cleanstr(r"OBIETTIVO\nUno\n\nCOME\nDue")=="OBIETTIVO\nUno\n\nCOME\nDue"
