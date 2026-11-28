"""CHASING v15: four no-stop sessions and complete native repetition recovery QA."""
import copy

import pytest

from scripts.ironman_jobs import chasing_swim_rebuild_20261018 as r


def test_all_71_swims_have_complete_native_recovery_steps():
    specs = r.build_specs()
    assert len(specs) == 71
    assert len({s["id"] for s in specs}) == 71
    continuous = {s["week"]: s["main"] for s in specs if s["kind"] == "cont"}
    assert continuous == {11: 2600, 13: 3000, 15: 3000, 19: 4000}
    assert sum(s["kind"] == "long" for s in specs) == 19
    assert r.design_gate(specs)["continuous_sessions"] == 4

    total_recoveries = 0
    for spec in specs:
        st = r.structure_for(spec["groups"])
        review = r.audit_native_swim_rests(spec["groups"], st)
        expected = sum(g["count"] * g["metres"] for g in spec["groups"])
        assert review["native_metres"] == expected == spec["metres"]
        assert st["primaryLengthMetric"] == "distance"
        assert st["polyline"]
        assert st["polyline"][-1][0] == 1
        assert all(0 <= point[0] <= 1 for point in st["polyline"])
        assert not any(step["length"]["unit"] == "second" and step["name"] != "Recupero"
                       for b in st["structure"] for step in b["steps"])
        total_recoveries += review["native_rest_groups"]
    assert total_recoveries > 100


def test_full_repetition_recovery_after_last_when_prescribed():
    cases = [(2, 1600, 45), (4, 700, 25), (8, 200, 20), (12, 100, 15)]
    for n, metres, seconds in cases:
        groups = [r._group(n, metres, "Fondo", (2, 3), "active", seconds)]
        st = r.structure_for(groups)
        result = r.audit_native_swim_rests(groups, st)
        assert result["native_rest_groups"] == n
        assert len(st["structure"]) == 1
        assert st["structure"][-1]["length"]["value"] == n
        assert st["structure"][-1]["steps"][-1]["name"] == "Recupero"
        assert all(b["begin"] <= b["end"] for b in st["structure"])


def test_recovery_gate_rejects_text_only_builder():
    groups = [r._group(8, 200, "CSS", (5, 6), "active", 20)]
    good = r.structure_for(groups)
    broken = copy.deepcopy(good)
    broken["structure"][0]["steps"] = broken["structure"][0]["steps"][:1]
    with pytest.raises(ValueError, match="BUILDER_DRIFT_STRUCTURE"):
        r.audit_native_swim_rests(groups, broken)


def test_no_stop_4000_remains_one_work_step():
    spec = next(s for s in r.build_specs() if s["week"] == 19 and s["kind"] == "cont")
    st = r.structure_for(spec["groups"])
    assert len(st["structure"]) == 1
    assert st["structure"][0]["steps"][0]["length"] == {"value": 4000, "unit": "meter"}
    assert all(s["name"] != "Recupero" for b in st["structure"] for s in b["steps"])
    assert r.audit_native_swim_rests(spec["groups"], st)["native_rest_groups"] == 0
