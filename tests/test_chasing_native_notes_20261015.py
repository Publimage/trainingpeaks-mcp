"""Acceptance gates for the approved 31 native CHASING notes, no provider calls."""
from pathlib import Path
import ast
import json
import sys
import re
import pytest

ROOT=Path(__file__).resolve().parents[1]
S=ROOT/"scripts"/"ironman_jobs"/"chasing_native_notes_core_20261015.py"
M=ROOT/"data"/"chasing_24w_native_notes_v1.json"
sys.path.insert(0,str(S.parent))
from chasing_native_notes_core_20261015 import (
    validate_manifest,validate_prefix,expected_key,dt,note_id,
    START,END,PLAN,OWNER
)

def test_canonical_manifest_is_approved_and_titles_are_clean():
    notes=validate_manifest()
    d=json.loads(M.read_text(encoding="utf-8"))
    assert d["source_document_id"] == "1zr41PjXW_y-xzs3jvH3dnhSmjHZr3LzLeFqqF9GQvyA"
    assert len(notes)==31 and len(set(x["title"] for x in notes))==31
    assert notes[0]["title"]=="START | Come usare Chasing the Slot"
    assert notes[1]["title"]=="INTENSITÀ | Watt, soglie e percezione"
    assert notes[-1]["title"]=="GARA | Pacing, imprevisti e ultimi controlli"
    assert all(not re.search(r"CHS-NOTE-|AF-IT-|^W\\d+",x["title"]) for x in notes)
    assert all(not re.search(r"CHS-NOTE-",x["description"]) for x in notes)
    assert all(" | " in x["title"] for x in notes)
    assert dt(notes[0])==START.isoformat()
    assert dt(notes[-1])=="2027-06-18"
    assert END>"2027-06-20"

def fake(note,n):
    return {"id":n,"planId":PLAN,"title":note["title"],
            "description":note["description"],"noteDate":dt(note),"attachments":[]}

def test_prefix_matches_sequential_provider_readback():
    notes=validate_manifest()
    for n in [0,1,3,11,21,31]:
        seq=[fake(x,i+1234) for i,x in enumerate(notes[:n])]
        validate_prefix(seq,notes,n)
    assert note_id(fake(notes[0],5001))==5001

def test_reject_duplicate_missing_or_coded_native_note():
    notes=validate_manifest()
    n=[fake(x,i+1234) for i,x in enumerate(notes[:3])]
    validate_prefix(n,notes,3)
    bad=[dict(x) for x in n]
    bad[0]["title"]="CHS-NOTE-001 | "+bad[0]["title"]
    with pytest.raises(RuntimeError,match="CONTENT_OR_PLACEMENT"):
        validate_prefix(bad,notes,3)
    with pytest.raises(RuntimeError,match="UNEXPECTED_NOTE_COUNT"):
        validate_prefix(n[:2],notes,3)
    dups=[dict(x) for x in n]
    dups[1]["id"]=dups[0]["id"]
    with pytest.raises(RuntimeError,match="NOTE_ID_MISSING_OR_DUPLICATED"):
        validate_prefix(dups,notes,3)

def test_guarded_writes_are_only_native_notes():
    source=S.read_text(encoding="utf-8")
    ast.parse(source)
    assert '"/plans/v1/plans/%d/calendarNote"' in source
    assert '"POST"' in source
    assert '"DELETE"' not in source and '"PUT"' not in source
    assert "_retry_on_401=False" in source
    assert "validate_prefix(current, notes, i+1)" in source
    assert "POST_RESULT_AMBIGUOUS_CHECK_PROVIDER" in source
    assert "p.get(\"workoutCount\") == 276" in source
    assert PLAN==685173 and OWNER==2116886
