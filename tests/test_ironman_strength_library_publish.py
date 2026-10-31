"""Offline exact-dose tests for the reusable native Strength Builder publisher."""
from types import SimpleNamespace

from scripts.ironman_jobs.ironman_strength_library_publish import (
    SOURCE_ITEM, DEST, OWNER, spec, blocks_for, native_blocks,
    semantically_correct, instructions, library_identity,
)

def test_source_is_reusable_and_complete():
    items=spec()
    assert len(items)==16
    assert SOURCE_ITEM=="330040"
    assert DEST==3891875
    assert sum(x["planned_duration_seconds"] for x in items)==845*60
    assert len({x["title"] for x in items})==16
    assert all(x["title"].count("|")==1 for x in items)
    assert all("WINTER" not in x["title"] and "W01" not in x["title"] for x in items)
    assert sum(1 for x in items for e in x["native_exercises"] if e["mapping"]!="NATIVE_EXACT")==3

def test_native_blocks_16_workouts_and_rest_notes():
    for item in spec():
        work=blocks_for(item)
        assert work[0]["type"]=="WarmUp"
        assert work[-1]["type"]=="CoolDown"
        assert "Short-foot" in work[-1]["notes"]
        assert "Toe Yoga" in work[-1]["notes"]
        assert len(work)==len(item["native_exercises"])+2
        assert all(b["exercises"] for b in work)
        assert all("Recupero tra le serie" in b["notes"] for b in work[1:-1]
                   if len(b["exercises"][0]["sets"])>1)
        assert all("Dopo l'esercizio" in b["notes"] or
                   "nessuna pausa finale" in b["notes"] for b in work[1:-1])
        native=native_blocks(item)
        assert len(native)==len(work)
        assert native[0]["blockType"]=="WarmUp"
        assert native[-1]["blockType"]=="CoolDown"
        assert all(p["coachNotes"] for b in native for p in b["prescriptions"])
        assert "DURATA PIANIFICATA" in instructions(item)
        assert str(item["planned_duration_seconds"]//60) in instructions(item)

def test_semantic_verifier_rejects_missing_or_wrong_planned_duration():
    item=spec()[0]
    w={"workoutType":"StructuredStrength","calendarId":None,"prescribedDate":None,
       "prescribedDurationInSeconds":item["planned_duration_seconds"],
       "title":item["title"],"instructions":instructions(item),
       "blocks":native_blocks(item)}
    obj={"libraryId":DEST,"title":item["title"],
         "workoutLibraryItemType":"ActivityWorkoutTemplate","workout":w}
    assert semantically_correct(obj,item)
    w["prescribedDurationInSeconds"]=None
    assert not semantically_correct(obj,item)

def test_library_is_strictly_coach_owned():
    data=[{"exerciseLibraryId":DEST, "libraryName":"ALBERTO FAZI ENDURANCE | Forza | IT",
           "ownerId":OWNER}]
    assert library_identity({"personId":OWNER},SimpleNamespace(is_error=False,data=data))
    assert not library_identity({"personId":1},SimpleNamespace(is_error=False,data=data))
    data[0]["ownerId"]=1
    assert not library_identity({"personId":OWNER},SimpleNamespace(is_error=False,data=data))
