"""Cross-plan classic workout patch parity; fake provider only, zero real TP writes."""
from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    Ledger, SecurityDenied, digest, run_changeset,
)
from scripts.ironman_jobs.ironman_unified_plan_workout_adapter import (
    ReviewedClassicPlanPatchAdapter,
)

OWNER = 2116886
REV = "b" * 40
SCOPE = "approved:offline-multi-plan"


class FakePlanProvider:
    def __init__(self, workouts):
        self.workouts = deepcopy(workouts)
        self.writes = []

    def read(self, change):
        t = change["target"]
        return deepcopy(self.workouts[t["container_id"], t["resource_id"]])

    def put_one(self, plan_id, workout_id, desired):
        self.writes.append((plan_id, workout_id))
        self.workouts[plan_id, workout_id] = deepcopy(desired)


def workout(workout_id):
    return {"workoutId": workout_id, "title": "Endurance | Bike",
            "description": "A2 steady", "totalTimePlanned": 1.5,
            "distancePlanned": 42.0, "sportId": 2, "day": "2027-04-01"}


def entry(name, plan_id, item, updated_title):
    desired = deepcopy(item)
    desired["title"] = updated_title
    return {
        "id": name, "kind": "plan.workout.patch",
        "target": {"provider": "trainingpeaks", "owner_id": OWNER,
                   "container_kind": "training_plan",
                   "container_id": plan_id, "resource_id": item["workoutId"]},
        "before_sha256": digest(item), "after_sha256": digest(desired),
        "depends_on": [], "payload": {"desired": desired, "fields": ["title"]},
    }


def manifest(*items):
    return {"schema": "IRONMAN_CHANGESET_V1", "request_id": "cross-plan-classic-001",
            "owner_id": OWNER, "reviewed_revision": REV,
            "approval_scope": SCOPE, "changes": list(items)}


def run(manifest_value, provider, path, *, execute=False, with_writer=True):
    journal = Ledger(path / "ledger.sqlite3")
    try:
        adapter = ReviewedClassicPlanPatchAdapter(
            reader=provider, put_one=provider.put_one if with_writer else None)
        return run_changeset(
            manifest_value, {"plan.workout.patch": adapter}, journal,
            execute=execute,
            reviewed_revision=REV if execute else None,
            approval_scope=SCOPE if execute else None,
            authorize_execution=lambda *_: True,  # Synthetic authority; no live provider.
        )
    finally:
        journal.close()


def test_same_code_updates_two_independent_plans_without_other_field_changes(tmp_path):
    a, b = workout(101), workout(202)
    provider = FakePlanProvider({(111001, 101): a, (222002, 202): b})
    request = manifest(entry("planA", 111001, a, "Endurance | Bike revised"),
                       entry("planB", 222002, b, "Endurance | Bike corrected"))
    preview = run(request, provider, tmp_path)
    assert [r["state"] for r in preview["results"]] == ["PREFLIGHT_PASS"] * 2
    assert provider.writes == []
    result = run(request, provider, tmp_path, execute=True)
    assert [r["state"] for r in result["results"]] == ["DONE_VERIFIED"] * 2
    assert provider.writes == [(111001, 101), (222002, 202)]
    for key, original in [((111001, 101), a), ((222002, 202), b)]:
        after = provider.workouts[key]
        assert {k: v for k, v in after.items() if k != "title"} == {
            k: v for k, v in original.items() if k != "title"}
    resumed = run(request, provider, tmp_path, execute=True)
    assert [r["state"] for r in resumed["results"]] == ["DONE_VERIFIED"] * 2
    assert len(provider.writes) == 2


def test_unreviewed_builder_or_duration_change_blocked_in_preview(tmp_path):
    original = workout(101)
    provider = FakePlanProvider({(111001, 101): original})
    ch = entry("one", 111001, original, "Endurance | New")
    ch["payload"]["desired"]["totalTimePlanned"] = 5
    ch["after_sha256"] = digest(ch["payload"]["desired"])
    result = run(manifest(ch), provider, tmp_path, execute=False)
    assert result["results"][0]["state"] == "FAILED_REVIEW"
    assert provider.writes == []


def test_invalid_duration_does_not_pass_proven_field_validator(tmp_path):
    original = workout(101)
    provider = FakePlanProvider({(111001, 101): original})
    ch = entry("one", 111001, original, "Endurance | New")
    ch["payload"]["fields"].append("totalTimePlanned")
    ch["payload"]["desired"]["totalTimePlanned"] = -12
    ch["after_sha256"] = digest(ch["payload"]["desired"])
    result = run(manifest(ch), provider, tmp_path)
    assert result["results"][0]["state"] == "FAILED_REVIEW"
    assert provider.writes == []


def test_writer_remains_disabled_unless_injected(tmp_path):
    original = workout(101)
    provider = FakePlanProvider({(111001, 101): original})
    request = manifest(entry("one", 111001, original, "Changed"))
    result = run(request, provider, tmp_path, execute=True, with_writer=False)
    assert result["results"][0]["state"] == "BLOCKED_SECURITY"
    assert provider.writes == []
