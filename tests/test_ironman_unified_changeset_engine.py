"""Universal change-set engine: synthetic provider only, zero real API calls."""
from __future__ import annotations

import json

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
     authorize_execution=lambda *_: True)


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
    assert all(x["source"] == "provider_rechecked" for x in again["results"])
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


def test_crashed_running_receipt_is_readback_only(ledger):
    before, after = {"v": 1}, {"v": 2}
    change = item("one", "plan.workout.patch", 52, before, after)
    m = make_manifest(change)
    adapter = FakeAdapter(before)
    run(m, {change["kind"]: adapter}, ledger, execute=False)
    ledger.claim(m["request_id"], change)
    ledger.set_state(m["request_id"], change["id"], "RUNNING")
    adapter.value = after.copy()  # provider applied, process crashed before receipt
    resumed = run(m, {change["kind"]: adapter}, ledger)
    assert resumed["results"][0]["state"] == "DONE_VERIFIED"
    assert resumed["results"][0]["source"] == "provider_reconciled_on_resume"
    assert adapter.writes == 0
    assert ledger.db.execute("SELECT COUNT(*) FROM resource_claims").fetchone()[0] == 0


def test_unavailable_postwrite_readback_is_uncertain_not_lost(ledger):
    before, after = {"v": 1}, {"v": 2}
    change = item("one", "plan.note.patch", 53, before, after)
    m = make_manifest(change)

    class LostRead(FakeAdapter):
        unavailable = True

        def read(self, spec):
            if self.writes and self.unavailable:
                raise OSError("synthetic provider readback unavailable")
            return super().read(spec)

    adapter = LostRead(before)
    result = run(m, {change["kind"]: adapter}, ledger)
    assert result["results"][0]["state"] == "UNKNOWN_NEEDS_READBACK"
    assert ledger.db.execute("SELECT COUNT(*) FROM resource_claims").fetchone()[0] == 1
    adapter.unavailable = False
    replay = run(m, {change["kind"]: adapter}, ledger)
    assert replay["results"][0]["state"] == "DONE_VERIFIED"
    assert replay["results"][0]["source"] == "provider_reconciled_on_resume"
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
    a = item("aaa", "plan.note.patch", 1, old, new)
    bad = make_manifest(a)
    bad["changes"][0]["target"]["owner_id"] = 5
    with pytest.raises(ChangeStop, match="TARGET_OWNER"):
        validate_manifest(bad)
    a = item("aaa", "plan.note.patch", 1, old, new)
    bad = make_manifest(a)
    bad["changes"][0]["target"]["container_kind"] = "athlete_calendar"
    with pytest.raises(ChangeStop, match="TARGET_CONTAINER"):
        validate_manifest(bad)
    c = item("ccc", "plan.note.patch", 3, old, new, depends=["ddd"])
    d = item("ddd", "plan.workout.patch", 4, old, new, depends=["ccc"])
    with pytest.raises(ChangeStop, match="DEPENDENCY_CYCLE"):
        validate_manifest(make_manifest(c, d))


def test_preimage_drift_is_blocked_not_published(ledger):
    before, live, after = {"v": 1}, {"v": 4}, {"v": 2}
    adapter = FakeAdapter(live)
    ch = item("one", "plan.note.patch", 33, before, after)
    out = run(make_manifest(ch), {ch["kind"]: adapter}, ledger)
    assert out["results"][0]["state"] == "BLOCKED_CONFLICT"
    assert adapter.writes == 0


def test_completed_item_provider_drift_on_resume_is_detected(ledger):
    before, after = {"v": 1}, {"v": 2}
    adapter = FakeAdapter(before)
    change = item("test1", "plan.workout.patch", 51, before, after)
    manifest = make_manifest(change)
    first = run(manifest, {change["kind"]: adapter}, ledger)
    assert first["results"][0]["state"] == "DONE_VERIFIED"
    adapter.value = {"v": 3}  # another operator changed the provider
    second = run(manifest, {change["kind"]: adapter}, ledger)
    assert second["results"][0]["state"] == "BLOCKED_CONFLICT"
    assert second["results"][0]["code"] == "POST_VERIFIED_PROVIDER_DRIFT"
    assert adapter.writes == 1


def test_deferred_dependency_resumes_after_uncertain_provider_reconciliation(ledger):
    """A dependent item must remain PENDING, not permanently SKIPPED."""
    before, after = {"value": "old"}, {"value": "new"}
    upstream = item("upstream", "plan.note.patch", 501, before, after)
    downstream = item("downstream", "plan.workout.patch", 502,
                      before, after, depends=["upstream"])
    manifest = make_manifest(upstream, downstream)
    upstream_provider = FakeAdapter(before, behavior="uncertain")
    downstream_provider = FakeAdapter(before)
    providers = {upstream["kind"]: upstream_provider,
                 downstream["kind"]: downstream_provider}

    first = run(manifest, providers, ledger)
    assert [x["state"] for x in first["results"]] == [
        "UNKNOWN_NEEDS_READBACK", "SKIPPED_DEPENDENCY"]
    assert first["request_state"] == "ACTION_INCOMPLETE"
    assert ledger.status(manifest["request_id"], "downstream") == "PENDING"
    assert downstream_provider.writes == 0

    # Synthetic late provider commit after a lost response: reconcile by READ,
    # never replay upstream, then complete the original dependent request.
    upstream_provider.value = after.copy()
    second = run(manifest, providers, ledger)
    assert [x["state"] for x in second["results"]] == [
        "DONE_VERIFIED", "DONE_VERIFIED"]
    assert second["request_state"] == "WORK_COMPLETE"
    assert second["provider_readback_verified"] is True
    assert upstream_provider.writes == 1
    assert downstream_provider.writes == 1


def test_unconfirmed_verified_dependency_blocks_new_writes_until_readback(ledger):
    before, after = {"value": 1}, {"value": 2}
    prior = item("prior", "plan.note.patch", 601, before, after)
    later = item("later", "plan.workout.patch", 602,
                 before, after, depends=["prior"])
    manifest = make_manifest(prior, later)

    class FlakyVerifiedRead(FakeAdapter):
        unavailable = True

        def read(self, spec):
            if self.unavailable:
                raise OSError("provider temporarily unreadable")
            return super().read(spec)

    prior_provider = FlakyVerifiedRead(after)
    later_provider = FakeAdapter(before)
    providers = {prior["kind"]: prior_provider, later["kind"]: later_provider}
    run(manifest, providers, ledger, execute=False)  # initialize PENDING ledger
    ledger.set_state(manifest["request_id"], "prior", "DONE_VERIFIED")
    failed = run(manifest, providers, ledger)
    assert failed["results"][0]["state"] == "UNKNOWN_NEEDS_READBACK"
    assert failed["results"][1]["state"] == "SKIPPED_DEPENDENCY"
    assert ledger.status(manifest["request_id"], "prior") == "UNKNOWN_NEEDS_READBACK"
    assert ledger.status(manifest["request_id"], "later") == "PENDING"
    assert later_provider.writes == 0
    prior_provider.unavailable = False
    recovered = run(manifest, providers, ledger)
    assert recovered["request_state"] == "WORK_COMPLETE"
    assert later_provider.writes == 1
    assert prior_provider.writes == 0


def test_temporary_preflight_read_error_does_not_abort_independent_work(ledger):
    before, after = {"v": 1}, {"v": 2}
    a = item("read_error", "plan.note.patch", 701, before, after)
    b = item("independent", "plan.workout.patch", 702, before, after)
    manifest = make_manifest(a, b)

    class FlakyRead(FakeAdapter):
        unavailable = True

        def read(self, spec):
            if self.unavailable:
                raise OSError("synthetic transient read failure")
            return super().read(spec)

    flaky = FlakyRead(before)
    independent = FakeAdapter(before)
    providers = {a["kind"]: flaky, b["kind"]: independent}
    first = run(manifest, providers, ledger)
    assert first["results"][0]["code"] == "PROVIDER_PREFLIGHT_READ_FAILED"
    assert first["results"][1]["state"] == "DONE_VERIFIED"
    assert first["request_state"] == "ACTION_INCOMPLETE"
    assert ledger.status(manifest["request_id"], "read_error") == "PENDING"
    assert flaky.writes == 0 and independent.writes == 1

    flaky.unavailable = False
    resumed = run(manifest, providers, ledger)
    assert resumed["request_state"] == "WORK_COMPLETE"
    assert flaky.writes == 1 and independent.writes == 1


def test_intermediate_verified_same_resource_state_recovers_against_final_image(ledger):
    """Readback failure must not strand an earlier edit later superseded."""
    before, middle, after = {"v": 1}, {"v": 2}, {"v": 3}
    first = item("first", "plan.note.patch", 801, before, middle)
    second = item("second", "plan.note.attachment.add", 801,
                  middle, after, depends=["first"])
    manifest = make_manifest(first, second)
    shared = FakeAdapter(before)

    class SharedAdapter:
        fail_first_read = False

        def read(self, spec):
            if self.fail_first_read and spec["id"] == "first":
                raise OSError("synthetic intermittent read")
            return shared.read(spec)

        def apply(self, spec):
            shared.apply(spec)

    adapter = SharedAdapter()
    providers = {first["kind"]: adapter, second["kind"]: adapter}
    assert run(manifest, providers, ledger)["request_state"] == "WORK_COMPLETE"
    adapter.fail_first_read = True
    lost = run(manifest, providers, ledger)
    assert lost["results"][0]["state"] == "UNKNOWN_NEEDS_READBACK"
    assert lost["request_state"] == "ACTION_INCOMPLETE"
    adapter.fail_first_read = False
    reconciled = run(manifest, providers, ledger)
    assert reconciled["request_state"] == "WORK_COMPLETE"
    assert all(x["state"] == "DONE_VERIFIED" for x in reconciled["results"])
    assert shared.writes == 2


def test_preview_and_denied_write_never_claim_request_complete(ledger):
    before, after = {"v": 1}, {"v": 2}
    change = item("one", "plan.note.patch", 901, before, after)
    manifest = make_manifest(change)
    provider = FakeAdapter(before, behavior="deny")
    preview = run(manifest, {change["kind"]: provider}, ledger, execute=False)
    assert preview["request_state"] == "PREVIEW_ONLY"
    assert preview["provider_readback_verified"] is False
    assert provider.writes == 0
    denied = run(manifest, {change["kind"]: provider}, ledger)
    assert denied["results"][0]["state"] == "BLOCKED_SECURITY"
    assert denied["request_state"] == "ACTION_INCOMPLETE"
    assert denied["provider_readback_verified"] is False


def test_legacy_persisted_skipped_dependency_is_migrated_safely(ledger):
    before, after = {"v": 1}, {"v": 2}
    predecessor = item("predecessor", "plan.note.patch", 1001, before, after)
    dependent = item("dependent", "plan.workout.patch", 1002,
                     before, after, depends=["predecessor"])
    manifest = make_manifest(predecessor, dependent)
    preceding_provider = FakeAdapter(after)
    dependent_provider = FakeAdapter(before)
    providers = {predecessor["kind"]: preceding_provider,
                 dependent["kind"]: dependent_provider}
    run(manifest, providers, ledger, execute=False)  # initialize ledger
    ledger.set_state(manifest["request_id"], "predecessor", "DONE_VERIFIED")
    # Fixture from an older ledger; new code must never persist this state.
    ledger.db.execute("UPDATE change_events SET state='SKIPPED_DEPENDENCY' WHERE change_id='dependent'")
    ledger.db.commit()
    recovered = run(manifest, providers, ledger)
    assert recovered["request_state"] == "WORK_COMPLETE"
    assert ledger.status(manifest["request_id"], "dependent") == "DONE_VERIFIED"
    assert preceding_provider.writes == 0 and dependent_provider.writes == 1


def test_typed_transient_provider_read_is_deferred_not_a_permanent_review_failure(ledger):
    before, after = {"v": 1}, {"v": 2}
    a = item("unavailable", "plan.note.patch", 1101, before, after)
    b = item("independent", "plan.workout.patch", 1102, before, after)
    manifest = make_manifest(a, b)

    class TypedReadFailure(FakeAdapter):
        unavailable = True

        def read(self, spec):
            if self.unavailable:
                raise ChangeStop("PLAN_NOTES_READ_FAILED")
            return super().read(spec)

    unavailable_provider = TypedReadFailure(before)
    independent_provider = FakeAdapter(before)
    providers = {a["kind"]: unavailable_provider,
                 b["kind"]: independent_provider}
    first = run(manifest, providers, ledger)
    assert first["results"][0]["state"] == "PENDING"
    assert first["results"][0]["code"] == "PROVIDER_PREFLIGHT_READ_UNAVAILABLE"
    assert first["results"][0]["read_code"] == "PLAN_NOTES_READ_FAILED"
    assert first["results"][1]["state"] == "DONE_VERIFIED"
    assert ledger.status(manifest["request_id"], "unavailable") == "PENDING"
    unavailable_provider.unavailable = False
    recovered = run(manifest, providers, ledger)
    assert recovered["request_state"] == "WORK_COMPLETE"
    assert unavailable_provider.writes == 1
    assert independent_provider.writes == 1


def test_generated_preview_scope_can_never_authorize_a_provider_write(ledger):
    before, after = {"v": 1}, {"v": 2}
    change = item("one", "plan.workout.patch", 2001, before, after)
    manifest = make_manifest(change)
    manifest["approval_scope"] = "PREVIEW_ONLY:" + manifest["request_id"]
    fake = FakeAdapter(before)
    assert run_changeset(manifest, {change["kind"]: fake}, ledger,
                         execute=False, authorize_execution=lambda *_: True)["request_state"] == "PREVIEW_ONLY"
    with pytest.raises(ChangeStop, match="PREVIEW_DRAFT_NOT_APPROVED"):
        run_changeset(manifest, {change["kind"]: fake}, ledger, execute=True,
                      reviewed_revision=manifest["reviewed_revision"],
                      approval_scope=manifest["approval_scope"], authorize_execution=lambda *_: True)
    assert fake.writes == 0



def test_concurrent_registration_of_same_changeset_is_idempotent(tmp_path):
    """Two SQLite connections race to create one durable request, not two."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    manifest = make_manifest(item(
        "same", "plan.workout.patch", 123, {"v": 1}, {"v": 2},
    ))
    manifest_sha = validate_manifest(manifest)
    path = tmp_path / "one-shared-ledger.sqlite3"
    ready = Barrier(2)

    def register():
        local_ledger = Ledger(path)
        try:
            ready.wait(timeout=5)
            local_ledger.setup(manifest, manifest_sha)
        finally:
            local_ledger.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = [executor.submit(register) for _ in range(2)]
        for job in jobs:
            job.result(timeout=15)

    ledger = Ledger(path)
    try:
        assert ledger.db.execute(
            "SELECT COUNT(*) FROM requests WHERE request_id=?",
            (manifest["request_id"],),
        ).fetchone()[0] == 1
        assert ledger.db.execute(
            "SELECT COUNT(*) FROM change_events WHERE request_id=?",
            (manifest["request_id"],),
        ).fetchone()[0] == 1
        assert ledger.status(manifest["request_id"], "same") == "PENDING"
        assert ledger.db.execute("SELECT COUNT(*) FROM resource_claims").fetchone()[0] == 0
    finally:
        ledger.close()


@pytest.mark.parametrize("prior_state", ["DONE_VERIFIED", "UNKNOWN_NEEDS_READBACK", "RUNNING"])
@pytest.mark.parametrize("execute", [False, True])
def test_explicit_readback_denial_is_terminal_and_never_retried(ledger, prior_state, execute):
    before, after = {"value": 1}, {"value": 2}
    change = item("denied-read", "plan.note.patch", 601, before, after)
    m = make_manifest(change)
    ledger.setup(m, validate_manifest(m))
    ledger.set_state(m["request_id"], change["id"], prior_state)

    class DeniedReader(FakeAdapter):
        denied = True
        reads = 0

        def read(self, spec):
            self.reads += 1
            if self.denied:
                raise SecurityDenied("SYNTHETIC_PROVIDER_ACCESS_DENIED")
            return super().read(spec)

    provider = DeniedReader(after)
    result = run(m, {change["kind"]: provider}, ledger, execute=execute)
    assert result["results"][0]["state"] == "BLOCKED_SECURITY"
    assert ledger.status(m["request_id"], change["id"]) == ("BLOCKED_SECURITY" if execute else prior_state)
    if execute:
        provider.denied = False
        reads = provider.reads
        retried = run(m, {change["kind"]: provider}, ledger)
        assert retried["results"][0]["state"] == "BLOCKED_SECURITY"
        assert provider.reads == reads
    assert provider.writes == 0


@pytest.mark.parametrize("behavior", ["normal", "committed_then_timeout", "deny"])
def test_postwrite_readback_denial_remains_security_stop_with_claim(ledger, behavior):
    before, after = {"value": 1}, {"value": 2}
    change = item("denied-postflight", "plan.workout.patch", 602, before, after)
    m = make_manifest(change)

    class PostflightDenied(FakeAdapter):
        def read(self, spec):
            if self.writes:
                raise SecurityDenied("SYNTHETIC_READBACK_DENIED")
            return super().read(spec)

    provider = PostflightDenied(before, behavior=behavior)
    result = run(m, {change["kind"]: provider}, ledger)
    assert result["results"][0]["state"] == "BLOCKED_SECURITY"
    assert ledger.status(m["request_id"], change["id"]) == "BLOCKED_SECURITY"
    assert ledger.db.execute("SELECT count(*) FROM resource_claims").fetchone() == (1,)
    assert run(m, {change["kind"]: provider}, ledger)["results"][0]["state"] == "BLOCKED_SECURITY"
    assert provider.writes == 1


def long_chain(count=1000, *, cycle=False):
    before, after = {"value": 1}, {"value": 2}
    changes = [item(f"change-{n:04d}", "plan.workout.patch", n + 1, before, after,
                    depends=[f"change-{n - 1:04d}"] if n else [])
               for n in range(count)]
    if cycle:
        changes[0]["depends_on"] = [changes[-1]["id"]]
    return make_manifest(*reversed(changes))


def test_supported_maximum_chain_does_not_depend_on_python_recursion_limit():
    manifest = long_chain()
    assert validate_manifest(manifest) == digest(manifest)


def test_cycle_at_supported_maximum_is_reported_as_contract_error():
    with pytest.raises(ChangeStop, match="DEPENDENCY_CYCLE"):
        validate_manifest(long_chain(cycle=True))


@pytest.mark.parametrize("dependencies", [[[]], [{}], [None], [True]])
def test_malformed_dependency_shape_returns_contract_error(dependencies):
    change = item("bad-dependency", "plan.workout.patch", 1, {"v": 1}, {"v": 2})
    change["depends_on"] = dependencies
    with pytest.raises(ChangeStop, match="DEPENDENCY_SHAPE"):
        validate_manifest(make_manifest(change))


def test_common_scheduler_preserves_ready_batch_input_order(ledger):
    before, after = {"value": 1}, {"value": 2}
    changes = [item("child", "plan.workout.patch", 1, before, after, depends=["parent"]),
               item("independent", "plan.workout.patch", 2, before, after),
               item("parent", "plan.workout.patch", 3, before, after),
               item("tail", "plan.workout.patch", 4, before, after, depends=["child"])]
    manifest = make_manifest(*changes)
    provider = FakeAdapter(before)
    result = run(manifest, {"plan.workout.patch": provider}, ledger, execute=False)
    assert [r["id"] for r in result["results"]] == ["independent", "parent", "child", "tail"]
    assert [x["id"] for x in manifest["changes"]] == ["child", "independent", "parent", "tail"]
    assert all(r["state"] == "PREFLIGHT_PASS" for r in result["results"])
    assert provider.writes == 0


def test_preview_schedules_supported_maximum_chain_without_stack_workaround(ledger):
    manifest = long_chain()
    provider = FakeAdapter({"value": 1})
    result = run(manifest, {"plan.workout.patch": provider}, ledger, execute=False)
    assert [r["id"] for r in result["results"]] == [f"change-{n:04d}" for n in range(1000)]
    assert all(r["state"] == "PREFLIGHT_PASS" for r in result["results"])
    assert result["request_state"] == "PREVIEW_ONLY" and provider.writes == 0


@pytest.mark.parametrize("problem,code", [("missing", "DEPENDENCY_MISSING"), ("cycle", "DEPENDENCY_CYCLE")])
def test_invalid_graph_stops_before_worker_ledger_or_provider_io(ledger, problem, code):
    before, after = {"value": 1}, {"value": 2}
    first = item("first", "plan.workout.patch", 1, before, after, depends=["second"])
    second = item("second", "plan.workout.patch", 2, before, after,
                  depends=["first"] if problem == "cycle" else ["missing"])

    class NoProviderIO(FakeAdapter):
        def read(self, spec):
            raise AssertionError("INVALID_GRAPH_MUST_NOT_READ_PROVIDER")

    provider = NoProviderIO(before)
    with pytest.raises(ChangeStop, match=code):
        run(make_manifest(first, second), {"plan.workout.patch": provider}, ledger)
    for table in ("requests", "change_events", "execution_workers", "resource_claims"):
        assert ledger.db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
    assert provider.writes == 0


@pytest.mark.parametrize("kind", [[], {}, None])
def test_malformed_kind_returns_domain_error_before_set_membership(kind):
    change = item("bad-kind", "plan.workout.patch", 1, {"v": 1}, {"v": 2})
    change["kind"] = kind
    with pytest.raises(ChangeStop, match="UNKNOWN_ADAPTER"):
        validate_manifest(make_manifest(change))
