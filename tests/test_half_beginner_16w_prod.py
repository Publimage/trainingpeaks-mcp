from scripts.ironman_jobs import half_beginner_16w_prod as m
def test_matrix_and_calendar():
 a=m.expected()
 assert len(a)==133
 assert len([r for r in a if r["sport"]=="ST"])==15
 assert len([r for r in a if r["sport"]!="ST"])==118
 assert sum(r["minutes"] for r in a if r["week"]==14)==624
 assert all(r["day"]!=0 for r in a)
 assert all(r["day"] in (1,4) for r in a if r["sport"]=="SW" and r["week"]<16)
 assert all(r["day"]==5 for r in a if r["sport"]=="RU" and r["minutes"]>=60 and r["week"]<16 and r["uid"].endswith("-SA-RU"))
 assert all(r["day"]==6 for r in a if r["sport"]=="BI" and r["minutes"]>=100)
 assert m.SW_METERS[13]>=1900
def test_structure_contract():
 for r in m.expected():
  if r["sport"]=="ST":continue
  name,desc,struct,meters=m.make(r)
  assert "70.3" not in name and "W01" not in name
  assert m.structure_len(struct)==(meters if meters else r["minutes"]*60)
  assert len(desc)>300
 assert m.make(next(r for r in m.expected() if r["week"]==13 and r["sport"]=="SW" and r["day"]==4))[3]>=1900
