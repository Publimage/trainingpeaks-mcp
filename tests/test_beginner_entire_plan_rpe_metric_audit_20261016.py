"""Scope and read-only safety checks for Beginner full native metric inventory."""
import ast
from pathlib import Path
PATH=Path("scripts/ironman_jobs/beginner_entire_plan_rpe_metric_audit_20261016.py")
def test_source_has_read_only_provider_calls_only():
    s=PATH.read_text(encoding="utf-8")
    ast.parse(s)
    assert "PLAN=679801" in s and "OWNER=2116886" in s
    assert "all_workouts" in s and "non_rpe" in s
    assert "metric!=\"rpe\"" in s
    for x in (".post(", ".put(", ".patch(", ".delete(", "._request("):
        assert x not in s
