"""No TrainingPeaks credentials, network calls, or provider writes in these tests."""
import asyncio
import copy
import json
import os
from pathlib import Path

import pytest

from scripts.ironman_jobs.plan_patch_batch_core import (
    PlanPatchStop, run_batch, sha256, validate_manifest,
)


class FakeGateway:
    def __init__(self, public=False):
        self.owner = 2116886
        self.plan = {"planId": 777, "title": "LAB | Release candidate",
                     "isPublic": public, "workoutCount": 2}
        self.workouts = {
            11: {"workoutId": 11, "workoutTypeValueId": 2, "title": "Old A",
                 "description": "Old", "duration": 1.0, "lastModifiedDate": "fixed"},
            12: {"workoutId": 12, "workoutTypeValueId": 3, "title": "Old B",
                 "description": "Old", "duration": 2.0, "lastModifiedDate": "fixed"},
        }
        self.writes = []
        self.fail_after_write = set()
        self.fail_before_write = set()

    async def get_owner_id(self):
        return self.owner

    async def get_plan(self, plan_id):
        assert plan_id == 777
        return copy.deepcopy(self.plan)

    async def get_workout(self, plan_id, workout_id):
        assert plan_id == 777
        return copy.deepcopy(self.workouts[workout_id])

    async def put_workout(self, plan_id, workout_id, payload):
        self.writes.append(workout_id)
        if workout_id in self.fail_before_write:
            raise TimeoutError("timed out before commit")
        self.workouts[workout_id] = copy.deepcopy(payload)
        if workout_id in self.fail_after_write:
            raise TimeoutError("timed out after commit")
        return True


def manifest(public=False):
    return {
        "schema": "IRONMAN_PLAN_PATCH_V1",
        "owner_id": 2116886,
        "plan_id": 777,
        "expected_title": "LAB | Release candidate",
        "expected_is_public": public,
        "expected_workout_count": 2,
        "scope": "trainingpeaks:lab-plan:777:patch-2-approved-titles-only",
        "items": [
            {"workout_id": 11, "before": {"title": "Old A"}, "after": {"title": "New A"}},
            {"workout_id": 12, "before": {"title": "Old B"}, "after": {"title": "New B"}},
        ],
    }


def run(coro):
    return asyncio.run(coro)


def test_preview_cannot_write(tmp_path):
    gateway = FakeGateway()
    spec = manifest()
    result = run(run_batch(spec, gateway, tmp_path / "journal.json"))
    assert result["status"] == "PREVIEW"
    assert result["provider_writes"] == 0
    assert not gateway.writes
    assert not (tmp_path / "journal.json").exists()


def test_real_path_requires_reviewed_digest_and_scope(tmp_path):
    gateway = FakeGateway()
    spec = manifest()
    for digest, ack in ((None, spec["scope"]), (sha256(spec), None)):
        with pytest.raises(PlanPatchStop):
            run(run_batch(spec, gateway, tmp_path / "journal.json", execute=True,
                          reviewed_manifest_sha256=digest, ack_scope=ack))
    assert gateway.writes == []


def test_complete_public_plan_without_visibility_change(tmp_path):
    gateway = FakeGateway(public=True)
    spec = manifest(public=True)
    ledger = tmp_path / "journal.json"
    result = run(run_batch(spec, gateway, ledger, execute=True,
                           reviewed_manifest_sha256=sha256(spec),
                           ack_scope=spec["scope"]))
    assert result["status"] == "VERIFIED"
    assert result["provider_writes"] == 2
    assert gateway.plan["isPublic"] is True
    assert gateway.plan["workoutCount"] == 2
    assert gateway.workouts[11]["duration"] == 1.0
    assert gateway.workouts[12]["description"] == "Old"
    assert json.loads(ledger.read_text())["items"] == {"11": "VERIFIED", "12": "VERIFIED"}
    assert os.stat(ledger).st_mode & 0o077 == 0
    second = run(run_batch(spec, gateway, ledger, execute=True,
                           reviewed_manifest_sha256=sha256(spec),
                           ack_scope=spec["scope"]))
    assert second["provider_writes"] == 0
    assert gateway.writes == [11, 12]


def test_transient_after_commit_reconciles_without_replay(tmp_path):
    gateway = FakeGateway()
    gateway.fail_after_write.add(11)
    spec = manifest()
    result = run(run_batch(spec, gateway, tmp_path / "journal.json", execute=True,
                           reviewed_manifest_sha256=sha256(spec), ack_scope=spec["scope"]))
    assert result["status"] == "VERIFIED"
    assert gateway.writes == [11, 12]


def test_uncertain_write_stops_and_requires_readback_review(tmp_path):
    gateway = FakeGateway()
    gateway.fail_before_write.add(12)
    spec = manifest()
    ledger = tmp_path / "journal.json"
    with pytest.raises(PlanPatchStop, match="UNCERTAIN_RESULT"):
        run(run_batch(spec, gateway, ledger, execute=True,
                      reviewed_manifest_sha256=sha256(spec), ack_scope=spec["scope"]))
    assert gateway.workouts[11]["title"] == "New A"
    assert gateway.workouts[12]["title"] == "Old B"
    assert json.loads(ledger.read_text())["items"] == {"11": "VERIFIED", "12": "UNCERTAIN"}
    gateway.fail_before_write.clear()
    with pytest.raises(PlanPatchStop, match="RECONCILE_FIRST"):
        run(run_batch(spec, gateway, ledger, execute=True,
                      reviewed_manifest_sha256=sha256(spec), ack_scope=spec["scope"]))
    assert gateway.writes == [11, 12]


def test_provider_drift_stops_prewrite(tmp_path):
    gateway = FakeGateway()
    spec = manifest()
    gateway.workouts[11]["title"] = "Concurrent coach edit"
    with pytest.raises(PlanPatchStop, match="TARGET_DRIFT"):
        run(run_batch(spec, gateway, tmp_path / "journal.json", execute=True,
                      reviewed_manifest_sha256=sha256(spec), ack_scope=spec["scope"]))
    assert gateway.writes == []


def test_manifest_change_cannot_reuse_journal(tmp_path):
    gateway = FakeGateway()
    spec = manifest()
    ledger = tmp_path / "journal.json"
    run(run_batch(spec, gateway, ledger, execute=True,
                  reviewed_manifest_sha256=sha256(spec), ack_scope=spec["scope"]))
    changed = manifest()
    changed["items"][1]["after"]["title"] = "Different title"
    with pytest.raises(PlanPatchStop, match="JOURNAL_MANIFEST_CONFLICT"):
        run(run_batch(changed, gateway, ledger, execute=True,
                      reviewed_manifest_sha256=sha256(changed), ack_scope=changed["scope"]))


def test_wrong_owner_or_plan_visibility_fails(tmp_path):
    spec = manifest(public=False)
    gateway = FakeGateway(public=True)
    with pytest.raises(PlanPatchStop, match="PLAN_VISIBILITY_CHANGED"):
        run(run_batch(spec, gateway, tmp_path / "j.json"))
    gateway.plan["isPublic"] = False
    gateway.owner = 999
    with pytest.raises(PlanPatchStop, match="OWNER_MISMATCH"):
        run(run_batch(spec, gateway, tmp_path / "j.json"))


def test_manifest_guards_duplicate_fields_and_literal_backslash_n():
    spec = manifest()
    spec["items"].append(copy.deepcopy(spec["items"][0]))
    with pytest.raises(PlanPatchStop, match="DUPLICATE"):
        validate_manifest(spec)
    spec = manifest()
    spec["items"][0]["before"] = {"isPublic": False}
    spec["items"][0]["after"] = {"isPublic": True}
    with pytest.raises(PlanPatchStop, match="FIELD_NOT_PERMITTED"):
        validate_manifest(spec)
    spec = manifest()
    spec["items"][0]["before"] = {"description": "old"}
    spec["items"][0]["after"] = {"description": r"OBIETTIVO\nCOME"}
    with pytest.raises(PlanPatchStop, match="LITERAL_NEWLINE_ESCAPE"):
        validate_manifest(spec)


def test_swim_duration_and_distance_required(tmp_path):
    spec = manifest()
    gateway = FakeGateway()
    gateway.workouts[11]["workoutTypeValueId"] = 1
    with pytest.raises(PlanPatchStop, match="SWIM_DISTANCE_REQUIRED"):
        run(run_batch(spec, gateway, tmp_path / "j.json"))
    gateway.workouts[11]["distancePlanned"] = 1500
    with pytest.raises(PlanPatchStop, match="SWIM_DURATION_REQUIRED"):
        run(run_batch(spec, gateway, tmp_path / "j.json"))


def test_manifest_no_arbitrary_builder_or_empty_text():
    spec = manifest()
    spec["items"][0]["before"] = {"structure": {"old": 1}}
    spec["items"][0]["after"] = {"structure": {"structure": [{"name": "x"}]}}
    with pytest.raises(PlanPatchStop, match="BUILDER_POLYLINE_REQUIRED"):
        validate_manifest(spec)


def test_ambiguous_result_resolves_when_later_provider_read_is_desired(tmp_path):
    gateway = FakeGateway()
    gateway.fail_before_write.add(12)
    spec = manifest()
    ledger = tmp_path / "journal.json"
    with pytest.raises(PlanPatchStop, match="UNCERTAIN_RESULT"):
        run(run_batch(spec, gateway, ledger, execute=True,
                      reviewed_manifest_sha256=sha256(spec), ack_scope=spec["scope"]))
    # The provider or a human may have reconciled the item after an ambiguous call.
    gateway.workouts[12]["title"] = "New B"
    gateway.fail_before_write.clear()
    result = run(run_batch(spec, gateway, ledger, execute=True,
                           reviewed_manifest_sha256=sha256(spec), ack_scope=spec["scope"]))
    assert result["status"] == "VERIFIED"
    assert result["provider_writes"] == 0
    assert gateway.writes == [11, 12]


def test_cross_process_execution_lock(tmp_path):
    import fcntl

    gateway = FakeGateway()
    spec = manifest()
    ledger = tmp_path / "journal.json"
    lock = ledger.parent / (ledger.name + ".lock")
    with lock.open("w") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(PlanPatchStop, match="ANOTHER_PLAN_BATCH_RUNNING"):
            run(run_batch(spec, gateway, ledger, execute=True,
                          reviewed_manifest_sha256=sha256(spec), ack_scope=spec["scope"]))
    assert not gateway.writes
