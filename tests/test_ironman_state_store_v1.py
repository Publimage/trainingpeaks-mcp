"""Offline acceptance: atomic persistence, idempotency, fail-closed conflicts."""
from pathlib import Path
import os
import sqlite3
import sys
import tempfile
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]/"scripts"/"ironman_jobs"
sys.path.insert(0,str(SCRIPTS))
from ironman_state_store_v1 import connect,record_verified_snapshot,read_snapshot,digest
from chasing_paceplus_ledger_seed_20261014 import verify,SETS

JOB="pilot-plan-685173-persistent-ledger-v1"
REF="drive:decision:2026-10-14"
PROVIDER="TrainingPeaks-Plan-Private"
def row(id=4001050288):
    return {"item_id":id,"relative_week":10,"duration_min":140,
            "provider_evidence_sha256":digest({"provider":id,"test":True})}

def test_atomic_idempotent_and_no_duplicate_event():
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/"case.sqlite3"
        db=connect(path)
        a=record_verified_snapshot(db,JOB,REF,PROVIDER,685173,[row()])
        b=record_verified_snapshot(db,JOB,REF,PROVIDER,685173,[row()])
        assert a["created"] is True and b["created"] is False
        x=read_snapshot(db,JOB)
        assert x["expected_items"]==1 and x["event_count"]==1
        assert x["items"][0]["state"]=="DONE_VERIFIED"
        with pytest.raises(AssertionError,match="CONFLICT_EXISTING"):
            record_verified_snapshot(db,JOB,REF,PROVIDER,685173,[row(999)])
        assert read_snapshot(db,JOB)==x
        db.close()
        # Open from a separate connection to emulate process restart.
        again=connect(path,read_only=True)
        assert read_snapshot(again,JOB)==x
        again.close()
        assert os.stat(path).st_mode & 0o777 == 0o600

def test_atomic_rollback_on_partial_write():
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/"rollback.sqlite3"
        db=connect(path)
        broken=[row(),row(4001053067)]
        broken[1]["provider_evidence_sha256"]=None
        with pytest.raises(sqlite3.IntegrityError):
            record_verified_snapshot(db,"bad-snapshot",REF,PROVIDER,685173,broken)
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM items").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM events").fetchone()[0]==0
        db.close()

def test_reject_duplicate_items_prewrite():
    with tempfile.TemporaryDirectory() as td:
        db=connect(Path(td)/"duplicate.sqlite3")
        with pytest.raises(RuntimeError,match="BAD_OR_DUPLICATE_ITEMS"):
            record_verified_snapshot(db,"dup",REF,PROVIDER,685173,[row(),row()])
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0]==0
        db.close()

def test_provider_shape_and_duration_gate_offline():
    wid=4001050288
    wk,wd,reps,orig,pace,plus,rest,lead,finish,easy=SETS[wid]
    w={"workoutId":wid,"workoutTypeValueId":2,
       "workoutDay":"2027-03-11T00:00:00",
       "totalTimePlanned":140/60,
       "description":"3x(10' Ironman Pace + 5' Ironman Pace+) senza numeri FTP",
       "structure":{"primaryLengthMetric":"duration","primaryIntensityMetric":"percentOfFtp",
        "structure":[{"type":"repetition","length":{"value":3,"unit":"repetition"},
           "steps":[
              {"name":"Ironman Pace","intensityClass":"active",
                "length":{"value":600,"unit":"second"},"targets":[{"minValue":71,"maxValue":75}]},
              {"name":"Ironman Pace+","intensityClass":"active",
                "length":{"value":300,"unit":"second"},"targets":[{"minValue":76,"maxValue":80}]},
              {"name":"Fondo facile","intensityClass":"rest",
                "length":{"value":900,"unit":"second"},"targets":[{"minValue":58,"maxValue":65}]}
              ]}]}}
    original=verify(w,wid)
    assert original["duration_min"]==140 and len(original["provider_evidence_sha256"])==64
    w["structure"]["structure"][0]["steps"][1]["targets"][0]["minValue"]=81
    with pytest.raises(RuntimeError,match="PACE_TARGET_DRIFT"):
        verify(w,wid)
