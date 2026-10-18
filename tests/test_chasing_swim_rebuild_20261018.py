from scripts.ironman_jobs import chasing_swim_rebuild_20261018 as x

def test_exact_scope_and_counts():
    specs=x.build_specs()
    assert x.PLAN==685173 and x.OWNER==2116886 and x.PERSON==6682479
    assert len(specs)==71 and len({s["id"] for s in specs})==71
    assert sum(s["week"]==24 for s in specs)==2
    assert all(sum(s["week"]==w for s in specs)==3 for w in range(1,24))

def test_progression_and_continuous_gate():
    specs=x.build_specs()
    gate=x.design_gate(specs)
    assert gate["continuous_max"]==4000
    assert gate["whole_4000"]==1
    assert gate["long_continuous_3k_plus"]>=10
    mains=[s["main"] for s in specs if s["kind"]=="cont"]
    assert any(v>=3500 for v in mains)
    assert any(v>=3800 for v in mains)
    assert 4000 in mains

def test_metres_and_equipment_variety():
    specs=x.build_specs()
    for s in specs:
        assert sum(g["count"]*g["metres"] for g in s["groups"])==s["metres"]
        assert s["metres"]>0 and s["minutes"]>0
    text="\n".join(s["description"].lower() for s in specs)
    assert text.count("palette")>=10
    assert text.count("pull buoy")>=10
    assert text.count("pinne")>=6
    for token in ("50 m","100 m","200 m","400 m"):
        assert token in text

def test_tests_are_only_intentional_repeated_protocol():
    specs=x.build_specs()
    tests=[s for s in specs if s["kind"]=="test"]
    assert [s["week"] for s in tests]==[1,5,9]
    assert all(s["metres"]==2500 and s["main"]==1500 for s in tests)
