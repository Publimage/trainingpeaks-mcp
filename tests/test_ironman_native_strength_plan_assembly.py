"""Offline contract tests for guarded WINTER 8W native plan assembly."""
import copy
from datetime import date
from scripts.ironman_jobs import ironman_native_strength_plan_assembly as p

def test_manifest_and_relative_dates():
    cfg,items=p.load_manifest()
    assert cfg["weeks"]==8 and len(items)==16
    assert cfg["plan_title"]==p.TITLE
    assert items[0]["week"]==1 and items[0]["weekday"]==3
    assert items[1]["week"]==1 and items[1]["weekday"]==5
    assert p.slot_date(items[0])=="2027-01-06"
    assert p.slot_date(items[1])=="2027-01-08"
    assert p.slot_date(items[-1])=="2027-02-26"
    assert date.fromisoformat(p.ANCHOR).weekday()==0
    assert sum(x["planned_duration_seconds"] for x in items)==50700
    assert all("W01" not in e["title"] and "WINTER" not in e["title"] for e in items)

def test_plan_identity_and_privacy_required():
    valid={"planId":123,"planPersonId":456,"ownerPersonId":p.OWNER,
           "isPublic":False,"price":None,"title":p.TITLE}
    assert p.is_valid_plan(valid,123)
    for key,changed in [("planId",999),("planPersonId",0),
                        ("ownerPersonId",0),("isPublic",True),
                        ("price",59),("title","OTHER")]:
        trial=dict(valid);trial[key]=changed
        assert not p.is_valid_plan(trial,123)

def test_native_clone_resets_identifiers_only():
    cfg,items=p.load_manifest()
    source={"id":"original","workoutType":"StructuredStrength",
            "title":items[0]["title"],"calendarId":None,
            "prescribedDate":None,"instructions":"Detailed",
            "prescribedDurationInSeconds":3000,
            "blocks":[{"id":"b1","blockType":"SingleExercise","title":"Squat",
                "coachNotes":"Recovery 120s","prescriptions":[{
                    "id":"p1","exercise":{"id":"131"},"coachNotes":"2x6 RPE6 rest 120s",
                    "sets":[{"id":"set1","parameterValues":[
                         {"id":"pv1","parameter":"Reps",
                          "prescribedValue":"6","executedValue":None}]}]}]}]}
    orig=copy.deepcopy(source)
    result=p.prepare(source,items[0],98765)
    assert source==orig
    assert p.semantic(result)==p.semantic(orig)
    assert result["calendarId"]==98765
    assert result["prescribedDate"]=="2027-01-06"
    assert result["id"]!="original"
    assert result["blocks"][0]["id"]!="b1"
    assert result["blocks"][0]["prescriptions"][0]["id"]!="p1"
    assert result["blocks"][0]["prescriptions"][0]["sets"][0]["id"]!="set1"
    assert result["blocks"][0]["prescriptions"][0]["sets"][0]["parameterValues"][0]["id"]!="pv1"

def test_semantic_detects_dose_and_recovery_drift():
    original={"workoutType":"StructuredStrength","instructions":"do it",
              "prescribedDurationInSeconds":3000,"blocks":[{
                  "blockType":"SingleExercise","title":"Squat","coachNotes":"120s",
                  "prescriptions":[{"exercise":{"id":"131"},"coachNotes":"120s",
                  "sets":[{"parameterValues":[{"parameter":"Reps","prescribedValue":"6"}]}]}]}]}
    for op in ("duration","reps","notes","exercise"):
        changed=copy.deepcopy(original)
        if op=="duration":changed["prescribedDurationInSeconds"]=2700
        elif op=="reps":changed["blocks"][0]["prescriptions"][0]["sets"][0]["parameterValues"][0]["prescribedValue"]="8"
        elif op=="notes":changed["blocks"][0]["prescriptions"][0]["coachNotes"]="60s"
        else:changed["blocks"][0]["prescriptions"][0]["exercise"]["id"]="144"
        assert p.semantic(changed)!=p.semantic(original)
