"""Universal change-set engine: synthetic provider only, zero real API calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    ChangeStop, Ledger, SecurityDenied, digest, run_changeset, validate_manifest,
)

OWNER = 2116886
REVISION = "a" * 40
SCOPE = "approved:test-shared-flow"


class FakeAdapter:
    def __init__(self, value: dict, *, behavior: str = "normal"):
        self.value = value.copy()
        self.behavior = behavior
        self.writes = 0

    def read(self, spec: dict) -> dict:
        return self.value.copy()

    def apply(self, spec: dict) -> None:
        self.writes += 1
        if self.behavior == "deny":
            raise SecurityDenied("AUTHORIZATION_DENIED")
        if self.behavior == "uncertain":
            raise TimeoutError("provider response disappeared")
        self.value = spec["payload"]["desired"].copy()
        if self.behavior == "committed_then_timeout":
            raise TimeoutError("response lost, provider applied change")


def item(change_id, kind, resource_id, before, after, depends=None, container="training_plan"):
    return {
        "id": change_id, "kind": kind,
        "target": {"provider": "trainingpeaks", "owner_id": OWNER,
                   "container_kind": container, "container_id": 684602,
                   "resource_id": resource_id},
        "before_sha256": digest(before), "after_sha256": digest(after),
        "depends_on": depends or [],
        "payload": {"desired": after},
    }


def make_manifest(*changes):
    return {
        "schema": "IRONMAN_CHANGESET_V1", "request_id": "fake-release-001",
        "owner_id": OWNER, "reviewed_revision": REVISION,
        "approval_scope": SCOPE, "changes": list(changes),
    }


@pytest.fixture
def ledger(tmp_path):
    db = Ledger(tmp_path / "ledger.sqlite3")
    yield db
    db.close()


def run(m, adapters, ledger, execute=True):
    return run_changeset(
        m, adapters, ledger, execute=execute,
        reviewed_revision=REVISION if execute else None,
        approval_scope=SCOPE if execute else None,
    )


def test_one_engine_handles_different_plan_resources_and_provider_readback(ledger):
    operations = [
        ("bike", "plan.workout.patch", 42),
        ("note", "plan.note.patch", 43),
        ("pdf", "plan.note.attachment.add", 44),
        ("strength", "plan.strength.relocate", 45),
        ("library", "library.workout.patch", 46),
    ]
    changes = []
    adapters = {}
    for key, kind, ident in operations:
        baseline = {"version": "before", "resource": ident}
        desired = {"version": "after", "resource": ident}
        changes.append(item(key, kind, ident, baseline, desired,
                            container="workout_library" if key == "library" else "training_plan"))
        adapters[kind] = FakeAdapter(baseline)
    m = make_manifest(*changes)
    preview = run(m, adapters, ledger, execute=False)
    assert all(x["state"] == "PREFLIGHT_PASS" for x in preview["results"])
    assert sum(a.writes for a in adapters.values()) == 0
    done = run(m, adapters, ledger)
    assert all(x["state"] == "DONE_VERIFIED" for x in done["results"])
    assert sum(a.writes for a in adapters.values()) == 5
    again = run(m, adapters, ledger)
    assert all(x["source"] == "ledger_verified" for x in again["results"])
    assert sum(a.writes for a in adapters.values()) == 5


def test_two_changes_same_note_are_sequenced_and_resource_lease_released(ledger):
    old, mid, new = {"files": [1]}, {"files": [1, 2]}, {"files": [2]}
    a = item("add", "plan.note.attachment.add", 2653899, old, mid)
    b = item("retire", "plan.note.attachment.retire", 2653899, mid, new, depends=["add"])
    shared = FakeAdapter(old)

    class SameNoteAdapter:
        def read(self, spec):
            return shared.read(spec)
        def apply(self, spec):
            shared.apply(spec)

    adapters = {a["kind"]: SameNoteAdapter(), b["kind"]: SameNoteAdapter()}
    out = run(make_manifest(a, b), adapters, ledger)
    assert [x["state"] for x in out["results"]] == ["DONE_VERIFIED", "DONE_VERIFIED"]
    assert shared.value == new and shared.writes == 2
    assert ledger.db.execute("SELECT COUNT(*) FROM resource_claims").fetchone()[0] == 0


def test_explicit_denial_is_not_retried_and_independent_task_continues(ledger):
    old, new = {"text": "old"}, {"text": "new"}
    denied = FakeAdapter(old, behavior="deny")
    allowed = FakeAdapter(old)
    a = item("one", "plan.workout.patch", 10, old, new)
    b = item("two", "plan.note.patch", 11, old, new)
    c = item("three", "plan.note.attachment.add", 12, old, new, depends=["one"])
    out = run(make_manifest(a, b, c),
              {a["kind"]: denied, b["kind"]: allowed, c["kind"]: FakeAdapter(old)}, ledger)
    assert [x["state"] for x in out["results"]] == [
        "BLOCKED_SECURITY", "DONE_VERIFIED", "SKIPPED_DEPENDENCY"
    ]
    assert denied.writes == 1 and allowed.writes == 1
    out2 = run(make_manifest(a, b, c),
               {a["kind"]: denied, b["kind"]: allowed, c["kind"]: FakeAdapter(old)}, ledger)
    assert denied.writes == 1
    assert out2["results"][0]["state"] == "BLOCKED_SECURITY"


def test_timeout_after_commit_reconciles_from_provider_without_duplicate(ledger):
    old, new = {"v": 1}, {"v": 2}
    adapter = FakeAdapter(old, behavior="committed_then_timeout")
    ch = item("one", "plan.note.patch", 33, old, new)
    result = run(make_manifest(ch), {ch["kind"]: adapter}, ledger)
    assert result["results"][0]["state"] == "DONE_VERIFIED"
    assert result["results"][0]["source"] == "provider_reconciled"
    assert adapter.writes == 1


def test_unknown_timeout_remains_claimed_and_no_auto_retry(ledger):
    old, new = {"v": 1}, {"v": 2}
    adapter = FakeAdapter(old, behavior="uncertain")
    ch = item("one", "plan.note.patch", 33, old, new)
    m = make_manifest(ch)
    r = run(m, {ch["kind"]: adapter}, ledger)
    assert r["results"][0]["state"] == "UNKNOWN_NEEDS_READBACK"
    assert ledger.db.execute("SELECT COUNT(*) FROM resource_claims").fetchone()[0] == 1
    again = run(m, {ch["kind"]: adapter}, ledger)
    assert again["results"][0]["code"] == "RECONCILIATION_REQUIRED"
    assert adapter.writes == 1


def test_manifest_reuse_with_different_payload_stops_before_write(ledger):
    old, new = {"v": 1}, {"v": 2}
    ch = item("one", "plan.note.patch", 33, old, new)
    m = make_manifest(ch)
    adapter = FakeAdapter(old)
    run(m, {ch["kind"]: adapter}, ledger, execute=False)
    tampered = json.loads(json.dumps(m))
    tampered["changes"][0]["payload"]["desired"] = {"v": 999}
    with pytest.raises(ChangeStop, match="IDEMPOTENCY_MANIFEST_DRIFT"):
        run(tampered, {ch["kind"]: adapter}, ledger)
    assert adapter.writes == 0


def test_rejects_cross_owner_athlete_calendar_bad_ids_and_cycles():
    old, new = {"a": 1}, {"a": 2}
    a = item("a", "plan.note.patch", 1, old, new)
    bad = make_manifest(a)
    bad["changes"][0]["target"]["owner_id"] = 5
    with pytest.raises(ChangeStop, match="TARGET_OWNER"):
        validate_manifest(bad)
    bad = make_manifest(a)
    bad["changes"][0]["target"]["container_kind"] = "athlete_calendar"
    with pytest.raises(ChangeStop, match="TARGET_CONTAINER"):
        validate_manifest(bad)
    c = item("c", "plan.note.patch", 3, old, new, depends=["d"])
    d = item("d", "plan.workout.patch", 4, old, new, depends=["c"])
    with pytest.raises(ChangeStop, match="DEPENDENCY_CYCLE"):
        validate_manifest(make_manifest(c, d))


def test_preimage_drift_is_blocked_not_published(ledger):
    before, live, after = {"v": 1}, {"v": 4}, {"v": 2}
    adapter = FakeAdapter(live)
    ch = item("one", "plan.note.patch", 33, before, after)
    out = run(make_manifest(ch), {ch["kind"]: adapter}, ledger)
    assert out["results"][0]["state"] == "BLOCKED_CONFLICT"
    assert adapter.writes == 0
