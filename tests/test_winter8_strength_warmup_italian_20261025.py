"""No-clone winter strength warmup and Italian labels: offline gates."""
from copy import deepcopy
from types import SimpleNamespace
from scripts.ironman_jobs import winter8_strength_warmup_italian_20261025 as s
from tp_mcp.tools.strength import _catalogue,_build_prescription,_u,_recount

def source_one():
    items,slots=s.source_rows()
    return items[1],slots[1]

def fake_workout(item):
    cat=_catalogue()
    blocks=[{"id":_u(),"blockType":"WarmUp","title":"Riscaldamento generale",
             "coachNotes":"7 min, ponte per i glutei e mobilita della caviglia.",
             "prescriptions":[
                 _build_prescription({"id":"579","sets":[{"Reps":8}],"notes":"glute bridge"},cat),
                 _build_prescription({"id":"5184","sets":[{"Duration":30}],"notes":"ankle roll"},cat)
             ]}]
    for e in item["native_exercises"]:
        param="RepsPerSide" if "per lato" in e["reps"] else "Reps"
        if "s" in e["reps"]:
            value={"Duration":20}
        else:
            value={param:int(e["reps"].split()[0].split("-")[0])}
        notes=f"RPE {e['rpe']}; recupero 90 secondi; Step Up e Coach Notes"
        blocks.append({"id":_u(),"blockType":"SingleExercise","title":e["title"],
            "coachNotes":notes,"prescriptions":[_build_prescription(
                {"id":str(e["id"]),"sets":[value for _ in range(e["sets"])],
                "notes":notes},cat)]})
    blocks.append({"id":_u(),"blockType":"CoolDown","title":"Foot core e controllo del piede",
        "coachNotes":"FOOT CORE: Short Foot, Toe Yoga e Toe Tap.",
        "prescriptions":[_build_prescription(
          {"id":"901","sets":[{"Reps":6},{"Reps":6}],"notes":"Toe Tap"},cat),
          _build_prescription({"id":"5184","sets":[{"Duration":30},{"Duration":30}],
          "notes":"Ankle Roll"},cat)]})
    return {"id":"some","workoutType":"StructuredStrength","title":item["title"],
            "calendarId":None,"prescribedDate":None,
            "prescribedDurationInSeconds":item["planned_duration_seconds"],
            "instructions":"Strength Builder. Follow the Coach Notes, Short Foot and Toe Yoga.",
            "blocks":blocks,"snapshot":_recount(blocks)}

def test_target_scope_and_unique_source_ids():
    rows,slots=s.source_rows()
    assert len(rows)==len(slots)==16
    assert s.LIB==3891875 and s.PLAN==689369 and s.PERSON==6709024
    assert len(s.RENAMES)==4
    assert sum(r["planned_duration_seconds"] for r in rows)==50700
    assert [x[0] for x in s.WARM_EX]==["5184","5305","475","7"]

def test_new_warmup_has_four_no_glute_duplicate_and_changes_no_training_dose():
    for item in s.source_rows()[0]:
        src=fake_workout(item)
        original=deepcopy(src)
        before=s.dose_blocks(src)
        current=s.apply(src,item)
        assert original==src
        assert s.expected_shape(current,item)
        assert s.dose_blocks(current)==before
        assert current["prescribedDurationInSeconds"]==src["prescribedDurationInSeconds"]
        assert len(current["instructions"]) <= 1000
        assert "W05" not in current["instructions"]
        assert "W09" not in current["instructions"]
        assert current["calendarId"]==src["calendarId"]
        assert len(current["blocks"][0]["prescriptions"])==4
        assert not any(str(q["exercise"]["id"])=="579"
                       for q in current["blocks"][0]["prescriptions"])
        assert "RISCALDAMENTO DINAMICO" in current["blocks"][0]["coachNotes"]
        assert current["blocks"][-1]["title"]=="Controllo e mobilita del piede"
        again=s.apply(current,item)
        assert again==current

def test_italian_titles_and_unaltered_native_embedded_exercise_names():
    items,slots=s.source_rows()
    it=s.apply(fake_workout(items[1]),items[1])
    assert it["title"]=="FORZA | Unilaterale e parte superiore 45 min"
    assert all("Coach Notes" not in it["instructions"] for _ in [0])
    assert "note dell'allenatore" in it["instructions"]
    assert [x["exercise"]["title"] for x in it["blocks"][0]["prescriptions"]]
    assert any("Ponte per i glutei" in b["title"] for b in it["blocks"][1:-1])
    assert s.IT["Glute bridge"]=="Ponte per i glutei"

def test_detects_old_warmup_drift():
    item,_=source_one()
    src=fake_workout(item)
    src["blocks"][0]["prescriptions"][0]["exercise"]["id"]="777"
    import pytest
    with pytest.raises(ValueError,match="OLD_WARMUP_NOT_EXPECTED"):
        s.apply(src,item)
