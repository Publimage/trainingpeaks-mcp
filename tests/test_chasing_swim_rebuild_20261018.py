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
    assert gate["continuous_sessions"]==4
    assert gate["long_continuous_3k_plus"]==3
    assert {s["week"]:s["main"] for s in specs if s["kind"]=="cont"}=={
        11:2600,13:3000,15:3000,19:4000
    }

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


def test_chasing_all_71_swims_full_native_repeats():
    specs=x.build_specs()
    assert len(specs)==71
    for spec in specs:
        groups=spec["groups"]
        result=x.structure_for(groups)
        audit=x.audit_native_swim_rests(groups,result)
        assert audit["native_metres"]==spec["metres"]
        assert result["primaryLengthMetric"]=="distance"
        assert result["primaryIntensityMetric"]=="rpe"
        assert result["polyline"]
        assert len(result["structure"])==len(groups)
        for group,block in zip(groups,result["structure"]):
            assert block["length"]["value"]==group["count"]
            assert block["type"]==("repetition" if group["count"]>1 else "step")
            rests=[step for step in block["steps"] if step["intensityClass"]=="rest"]
            if group["count"]>1 and group["recovery"]>0:
                assert len(rests)==1
                assert rests[0]["name"]=="Recupero"
                assert rests[0]["length"]=={"value":group["recovery"],"unit":"second"}
            else:
                assert not rests


def test_chasing_validator_rejects_detached_last_rep_and_english_rest():
    import copy
    import pytest

    spec=next(s for s in x.build_specs() if any(g["count"]>1 and g["recovery"]>0
                                                  for g in s["groups"]))
    good=x.structure_for(spec["groups"])
    bad=copy.deepcopy(good)
    block=next(b for b in bad["structure"] if b["type"]=="repetition" and
               len(b["steps"])==2)
    block["length"]["value"]-=1
    with pytest.raises(ValueError,match="BUILDER_DRIFT_STRUCTURE"):
        x.audit_native_swim_rests(spec["groups"],bad)
    bad=copy.deepcopy(good)
    block=next(b for b in bad["structure"] if b["type"]=="repetition" and
               len(b["steps"])==2)
    block["steps"][1]["name"]="Recover"
    with pytest.raises(ValueError,match="BUILDER_DRIFT_STRUCTURE"):
        x.audit_native_swim_rests(spec["groups"],bad)


def test_shared_builder_generic_duration_and_distance():
    from tp_mcp.tools.library import build_native_repeat_structure, audit_native_repeat_structure
    work={"name":"Lavoro","length":{"value":180,"unit":"second"},
          "targets":[{"minValue":80,"maxValue":90}],
          "intensityClass":"active","openDuration":False}
    rest={"name":"Recupero","length":{"value":60,"unit":"second"},
          "targets":[{"minValue":40,"maxValue":50}],
          "intensityClass":"rest","openDuration":False}
    groups=[{"count":3,"steps":[work,rest]}]
    compiled=build_native_repeat_structure(groups,length_metric="duration",
                                            intensity_metric="percentOfFtp")
    assert compiled["structure"][0]["length"]["value"]==3
    assert compiled["structure"][-1]["end"]==720
    assert len(compiled["polyline"])>=4
    assert audit_native_repeat_structure(groups,compiled,length_metric="duration",
                                          intensity_metric="percentOfFtp")["native_rest_events"]==3
    metres={"name":"50 m","length":{"value":50,"unit":"meter"},
            "targets":[{"minValue":2,"maxValue":3}],
            "intensityClass":"active","openDuration":False}
    seconds={"name":"Recupero","length":{"value":15,"unit":"second"},
             "targets":[{"minValue":0,"maxValue":0}],
             "intensityClass":"rest","openDuration":False}
    distance_groups=[{"count":6,"steps":[metres,seconds]}]
    swim=build_native_repeat_structure(distance_groups,length_metric="distance",
                                        intensity_metric="rpe")
    assert swim["structure"][-1]["end"]==300
    assert swim["polyline"][-1][0]==1
    assert audit_native_repeat_structure(distance_groups,swim,length_metric="distance",
                                          intensity_metric="rpe")["native_rest_events"]==6


def test_standard_workout_tool_uses_same_shared_repeat_compiler():
    from tp_mcp.tools.structure import parse_structure_input, build_wire_structure
    from tp_mcp.tools.library import build_native_repeat_structure

    payload={
        "primaryIntensityMetric":"percentOfFtp",
        "steps":[
            {"type":"repetition","reps":3,"steps":[
                {"name":"Steady","duration_seconds":180,"intensity_min":80,
                 "intensity_max":90,"intensityClass":"active"},
                {"name":"Recupero","duration_seconds":60,"intensity_min":40,
                 "intensity_max":50,"intensityClass":"rest"},
            ]},
            {"name":"Fondo","duration_seconds":600,"intensity_min":60,
             "intensity_max":70,"intensityClass":"active"},
        ],
    }
    parsed=parse_structure_input(payload)
    from tp_mcp.tools.structure import _build_step_wire
    expected=build_native_repeat_structure(
        [{"count":3,"steps":[_build_step_wire(st) for st in parsed.steps[0].steps]},
         {"count":1,"steps":[_build_step_wire(parsed.steps[1])]}],
        length_metric="duration",intensity_metric="percentOfFtp",
    )
    actual=build_wire_structure(parsed)
    assert actual==expected
    assert actual["structure"][0]["length"]["value"]==3
    assert actual["structure"][0]["steps"][-1]["name"]=="Recupero"
    assert actual["structure"][-1]["end"]==1320
    assert actual["primaryLengthMetric"]=="duration"
    assert actual["structure"][0]["steps"][1]["length"]=={"value":60,"unit":"second"}
