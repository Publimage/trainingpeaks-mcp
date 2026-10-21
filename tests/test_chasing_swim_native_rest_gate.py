"""Regression tests: every prescribed swim recovery must be executable, not text only."""
import pytest
from scripts.ironman_jobs import chasing_swim_rebuild_20261018 as r


def test_all_chasing_swim_repetitions_have_native_timed_recover(monkeypatch):
    # Check the raw builder contract; real provider rendering is a separate gate.
    monkeypatch.setattr(r, "_ensure_structure_preview", lambda s: s)
    specs = r.build_specs()
    assert len(specs) == 71
    assert sum(s["kind"] == "cont" for s in specs) == 23
    total_rest_groups = 0
    for spec in specs:
        st = r.structure_for(spec["groups"])
        report = r.audit_native_swim_rests(spec["groups"], st)
        total_rest_groups += report["native_rest_groups"]
        assert st["primaryLengthMetric"] == "distance"
        assert sum(g["count"] * g["metres"] for g in spec["groups"]) == spec["metres"]
        for g, block in zip(spec["groups"], st["structure"]):
            recover = [s for s in block["steps"] if s["name"] == "Recover"]
            assert len(recover) == (1 if g["count"] > 1 and g["recovery"] else 0)
            if recover:
                assert recover[0]["length"] == {"value": g["recovery"], "unit": "second"}
                assert recover[0]["targets"] == [{"minValue": 0, "maxValue": 0}]
                assert recover[0]["intensityClass"] == "rest"
    assert total_rest_groups > 50


def test_rest_gate_refuses_text_only_builder(monkeypatch):
    monkeypatch.setattr(r, "_ensure_structure_preview", lambda s: s)
    groups = [r._group(8, 200, "CSS", (5, 6), "active", 20)]
    good = r.structure_for(groups)
    bad = {"structure": [{"steps": good["structure"][0]["steps"][:1]}]}
    with pytest.raises(RuntimeError, match="SWIM_NATIVE_RESTS_NOT_EQUAL_TEXT"):
        r.audit_native_swim_rests(groups, bad)


def test_true_continuous_swim_is_left_without_artificial_recovery(monkeypatch):
    monkeypatch.setattr(r, "_ensure_structure_preview", lambda s: s)
    groups = r.build_groups(19, "cont", 4000, 4000)
    st = r.structure_for(groups)
    assert st["structure"][0]["steps"][0]["length"] == {"value": 4000, "unit": "meter"}
    assert all(s["name"] != "Recover" for b in st["structure"] for s in b["steps"])
    assert r.audit_native_swim_rests(groups, st)["native_rest_groups"] == 0
