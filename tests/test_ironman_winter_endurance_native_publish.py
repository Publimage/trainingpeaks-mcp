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

def test_swim_recovers_exactly_n_minus_one():
    _,items=p.source()
    for e in items:
        if e["sport"]!="SW":continue
        structure=p.compiled(e)["structure"]
        found=sum(b["length"]["value"] for b in structure["structure"]
                  if b["type"]=="repetition" and
                  any(s["name"]=="Recover" for s in b["steps"]))
        expected=sum(g["count"]-1 for g in e["groups"] if g["rest"]>0)
        assert found==expected
        for b in structure["structure"]:
            for s in b["steps"]:
                if s["name"]=="Recover":
                    assert s["length"]["unit"]=="second"
                    assert s["targets"]==[{"minValue":0,"maxValue":0}]
                    assert s["intensityClass"]=="rest"

def test_steady_recoveries_only_between_repetitions():
    _,items=p.source()
    for e in items:
        if e["sport"]!="BI" or e["week"] not in (6,7) or e["weekday"]!=2:continue
        builder=p.compiled(e)["structure"]["structure"]
        rest=sum(b["length"]["value"] for b in builder if b["type"]=="repetition"
                 for x in b["steps"] if x["intensityClass"]=="rest")
        assert rest==2
        assert all(len(x["targets"])==1 for b in builder for x in b["steps"])
        assert builder[-1]["end"]==e["minutes"]*60

def test_golden_and_placement():
    _,items=p.source()
    gold=p.is_golden_preflight(items)
    assert set(gold)=={"SW","BI","RU"}
    assert all(v["week"]==1 for v in gold.values())
    assert p.dt(gold["SW"])=="2027-01-05"
    assert p.dt(gold["RU"])=="2027-01-06"
    assert p.dt(items[-1])=="2027-02-28"
