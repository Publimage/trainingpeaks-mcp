"""Offline golden-first validation of Winter 8W native Builder publication."""
from collections import Counter
from datetime import date
from scripts.ironman_jobs import ironman_winter_endurance_native_publish as p

def test_source_counts_and_months():
    config,items=p.source()
    assert len(items)==58
    assert Counter(x["sport"] for x in items)==Counter({"SW":16,"BI":20,"RU":22})
    assert sum(x["minutes"] for x in items)==3250
    assert sum(x.get("metres",0) for x in items)==34600
    assert p.ANCHOR.weekday()==0
    assert (min(x["week"] for x in items),max(x["week"] for x in items))==(1,8)
    assert all(x["title"].count("|")==1 and not x["title"].startswith("WINTER") for x in items)

def test_all_builder_steps_and_polyline():
    _,items=p.source()
    unique={}
    for x in items:
        k=(x["sport"],x["title"])
        actual=p.compiled(x)
        assert actual["exerciseLibraryId"]==p.LIB[x["sport"]]
        assert actual["workoutTypeId"]==p.SPORT[x["sport"]]
        assert actual["structure"]["polyline"]
        assert actual["totalTimePlanned"]==x["minutes"]/60
        assert "RPE" in actual["description"]
        assert "FUELING" in actual["description"]
        if x["sport"]=="SW":
            assert actual["distancePlanned"]==x["metres"]
            assert actual["structure"]["primaryLengthMetric"]=="distance"
            assert actual["structure"]["primaryIntensityMetric"]=="rpe"
            assert actual["structure"]["structure"][-1]["end"]==x["metres"]
        else:
            assert actual["structure"]["primaryLengthMetric"]=="duration"
            assert actual["structure"]["primaryIntensityMetric"]==(
                "percentOfFtp" if x["sport"]=="BI" else "percentOfThresholdPace")
            assert actual["structure"]["structure"][-1]["end"]==x["minutes"]*60
        for g in actual["structure"]["structure"]:
            for step in g["steps"]:
                assert step["targets"]
                assert 0<=step["targets"][0]["minValue"]<=step["targets"][0]["maxValue"]
        if k in unique:
            assert unique[k]==actual
        unique[k]=actual
    assert len(unique)==51

def test_swim_full_repeats_with_last_recovery_and_italian_labels():
    _,items=p.source()
    seen=0
    for e in items:
        if e["sport"]!="SW":continue
        seen+=1
        structured=p.compiled(e)["structure"]
        blocks=structured["structure"]
        assert len(blocks)==len(e["groups"])
        total_rest=0
        for original,block in zip(e["groups"],blocks):
            assert block["length"]["value"]==original["count"]
            assert block["type"]==("repetition" if original["count"]>1 else "step")
            assert block["steps"][0]["length"]=={"value":original["distance"],"unit":"meter"}
            rests=[step for step in block["steps"] if step["intensityClass"]=="rest"]
            if original["count"]>1 and original["rest"]>0:
                assert len(rests)==1
                assert rests[0]["name"]=="Recupero"
                assert rests[0]["length"]=={"value":original["rest"],"unit":"second"}
                assert rests[0]["targets"]==[{"minValue":0,"maxValue":0}]
                total_rest+=original["count"]
            else:
                assert not rests
        assert total_rest==sum(g["count"] for g in e["groups"]
                               if g["count"]>1 and g["rest"]>0)
        assert structured["polyline"]
        assert blocks[-1]["end"]==e["metres"]
    assert seen==16


def test_winter_swim_validator_rejects_split_last_repetition():
    import copy
    _,items=p.source()
    e=next(x for x in items if x["sport"]=="SW")
    native=[p.swimming_group(g["count"],g["distance"],g["label"],tuple(g["rpe"]),
            "warmUp" if i==0 else "coolDown" if "Defaticamento" in g["label"]
            else "active",g["rest"]) for i,g in enumerate(e["groups"])]
    valid=p.swimming_builder(native)
    assert p.audit_swimming(native,valid)["native_metres"]==e["metres"]
    broken=copy.deepcopy(valid)
    ix=next(i for i,b in enumerate(broken["structure"]) if
            b["type"]=="repetition" and len(b["steps"])==2)
    broken["structure"][ix]["length"]["value"]-=1
    import pytest
    with pytest.raises(ValueError,match="BUILDER_DRIFT_STRUCTURE"):
        p.audit_swimming(native,broken)


def test_steady_complete_repeats_and_unchanged_total_minutes():
    _,items=p.source()
    targets=[e for e in items if e["sport"]=="BI" and any(
            z[0]=="steady" for z in e["blocks"])]
    assert len(targets)==2
    assert sorted(e["minutes"] for e in targets)==[70,75]
    for e in targets:
        blocks=p.compiled(e)["structure"]["structure"]
        steady=[b for b in blocks if b["type"]=="repetition" and
                b["steps"][0]["name"].startswith("Steady")]
        assert len(steady)==1 and steady[0]["length"]["value"]==3
        assert len(steady[0]["steps"])==2
        assert steady[0]["steps"][1]["intensityClass"]=="rest"
        recovery_min=next(z[1] for z in e["blocks"] if z[0]=="rest")
        endurance_min=next(z[1] for z in e["blocks"] if z[0]=="endurance")
        after=next(b["steps"][0]["length"]["value"] for b in blocks
                   if b["steps"][0]["name"].startswith("Fondo aerobico"))
        assert after==(endurance_min-recovery_min)*60
        assert blocks[-1]["end"]==e["minutes"]*60


def test_golden_and_placement():
    _,items=p.source()
    gold=p.is_golden_preflight(items)
    assert set(gold)=={"SW","BI","RU"}
    assert all(v["week"]==1 for v in gold.values())
    assert p.dt(gold["SW"])=="2027-01-05"
    assert p.dt(gold["RU"])=="2027-01-06"
    assert p.dt(items[-1])=="2027-02-28"
