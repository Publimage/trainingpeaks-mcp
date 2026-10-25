"""Offline guards for the Intermediate native read-only plan baseline job."""
from pathlib import Path
import ast

SOURCE = Path(__file__).resolve().parents[1] / "scripts/ironman_jobs/intermediate_native_baseline_readonly_20261022.py"

def test_compiles_and_is_scoped():
    raw = SOURCE.read_text(encoding="utf-8")
    ast.parse(raw)
    assert "PLAN=684602" in raw
    assert "PERSON=6678583" in raw
    assert "OWNER=2116886" in raw
    assert "isPublic\") is True" in raw
    assert "workoutCount\")==259" in raw

def test_provider_calls_are_read_only():
    raw = SOURCE.read_text(encoding="utf-8")
    for forbidden in ("await c.post(", "await c.put(", "await c.delete(",
                      "await h.post(", "await h.put(", "await h.delete(",
                      "os.system(", "subprocess.", "write_text(", "write_bytes("):
        assert forbidden not in raw, forbidden
