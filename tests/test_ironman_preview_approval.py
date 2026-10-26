"""Real DraftStore/Changeset integration; synthetic provider, no network."""
import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from scripts.ironman_jobs.ironman_dynamic_request_store import (
    DraftStop, DraftStore, compile_preview_changeset, prepare_draft,
)
from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    ChangeStop, Ledger, SecurityDenied, digest, run_changeset,
)

REVISION = "a" * 40
SCOPE = "approved:synthetic-review"


class Provider:
    def __init__(self):
        self.value = {"title": "before"}
        self.writes = 0
        self.denied = False

    def read(self, spec):
        return dict(self.value)

    def apply(self, spec):
        self.writes += 1
        if self.denied:
            raise SecurityDenied("EXPLICIT_DENIAL")
        self.value = dict(spec["payload"]["desired"])


@pytest.fixture
def context(tmp_path):
    provider = Provider()
    target = {"provider": "trainingpeaks", "owner_id": 2116886,
              "container_kind": "training_plan", "container_id": 501,
              "resource_id": 31}
    draft = prepare_draft([{
        "id": "patch01", "kind": "plan.workout.patch", "target": target,
        "before_sha256": digest(provider.value), "depends_on": [],
        "payload": {"desired": {"title": "after"}},
    }], request_key="synthetic-approval-request")
    store = DraftStore(tmp_path / "drafts.sqlite3")
    store.store(draft)
    manifest = compile_preview_changeset(
        draft, {"patch01": {"title": "after"}}, pinned_revision=REVISION)["manifest"]
    ledger = Ledger(":memory:")
    try:
        receipt = run_changeset(manifest, {"plan.workout.patch": provider}, ledger)
    finally:
        ledger.close()
    receipt.update(provider_writes=0, publication_enabled=False)
    preview = store.store_preview(manifest, receipt)["preview_sha256"]
    ctx = dict(store=store, provider=provider, draft=draft, manifest=manifest,
               receipt=receipt, preview=preview, path=store.path,
               review=dict(approved_revision=REVISION, approval_scope=SCOPE,
                           requested_targets=[{"kind": "plan.workout.patch", "target": target}]))
    yield ctx
    store.close()


def approve(ctx):
    return ctx["store"].record_approval(
        ctx["draft"]["request_id"], ctx["preview"], **ctx["review"])


def bind(ctx, approval):
    return ctx["store"].bind_execution(
        ctx["draft"]["request_id"], ctx["preview"],
        approval["approval_sha256"], **ctx["review"])


def test_approval_and_binding_resume_after_reopen_without_rewriting_preview(context):
    ctx = context
    approval = approve(ctx)
    assert approval["reused"] is False
    assert approve(ctx)["reused"] is True
    ctx["store"].close()
    ctx["store"] = DraftStore(ctx["path"])
    execution = bind(ctx, approval)
    assert execution["reused"] is False
    assert bind(ctx, approval)["reused"] is True
    assert execution["manifest_sha256"] == digest(execution["manifest"])
    assert ctx["store"].get_preview(ctx["draft"]["request_id"], ctx["preview"])["manifest"] == ctx["manifest"]
    assert ctx["store"].get(ctx["draft"]["request_id"]) == ctx["draft"]
    assert ctx["provider"].writes == 0
    assert execution["publication_enabled"] is False


@pytest.mark.parametrize("field,value,error", [
    ("approved_revision", "b" * 40, "REVISION_NOT_APPROVED"),
    ("approved_revision", None, "REVISION_NOT_APPROVED"),
    ("approval_scope", "PREVIEW_ONLY:fake", "APPROVAL_SCOPE_REQUIRED"),
    ("approval_scope", "", "APPROVAL_SCOPE_REQUIRED"),
    ("requested_targets", [], "APPROVAL_TARGET_MISMATCH"),
    ("requested_targets", None, "APPROVAL_TARGET_MISMATCH"),
])
def test_independent_review_context_required_on_approval_and_every_resume(context, field, value, error):
    ctx = context
    approval = approve(ctx)
    ctx["review"][field] = value
    with pytest.raises(DraftStop, match=error):
        approve(ctx)
    with pytest.raises(DraftStop, match=error):
        bind(ctx, approval)
    assert ctx["store"].db.execute("SELECT count(*) FROM execution_bindings").fetchone() == (0,)
    assert not ctx["store"].db.in_transaction


@pytest.mark.parametrize("field,value", [
    ("owner_id", 123), ("container_id", 902), ("resource_id", 32),
    ("container_kind", "athlete_calendar"), ("provider", "other"),
])
def test_review_cannot_retarget_a_preview(context, field, value):
    context["review"]["requested_targets"][0]["target"][field] = value
    with pytest.raises(DraftStop, match="APPROVAL_TARGET_MISMATCH"):
        approve(context)


def test_missing_approval_and_forged_or_corrupt_record_fail_closed(context):
    ctx = context
    with pytest.raises(DraftStop, match="APPROVAL_BINDING_MISMATCH"):
        bind(ctx, {"approval_sha256": "f" * 64})
    approval = approve(ctx)
    ctx["store"].db.execute("DELETE FROM preview_approvals")
    ctx["store"].db.commit()
    with pytest.raises(DraftStop, match="APPROVAL_NOT_FOUND"):
        bind(ctx, approval)
    approve(ctx)
    ctx["store"].db.execute("UPDATE preview_approvals SET payload='{}'")
    ctx["store"].db.commit()
    for operation in (lambda: approve(ctx), lambda: bind(ctx, approval)):
        with pytest.raises(DraftStop, match="APPROVAL_RECORD_CORRUPT"):
            operation()


def revised_preview(ctx):
    manifest = copy.deepcopy(ctx["manifest"])
    manifest["reviewed_revision"] = "b" * 40
    receipt = {**ctx["receipt"], "manifest_sha256": digest(manifest)}
    preview = ctx["store"].store_preview(manifest, receipt)["preview_sha256"]
    return {**ctx, "manifest": manifest, "preview": preview,
            "review": {**ctx["review"], "approved_revision": "b" * 40}}


def test_approval_cannot_transfer_to_new_revision_or_scope(context):
    approval = approve(context)
    newer = revised_preview(context)
    with pytest.raises(DraftStop, match="APPROVAL_BINDING_MISMATCH"):
        bind(newer, approval)
    context["review"]["approval_scope"] = "approved:other-scope"
    with pytest.raises(DraftStop, match="APPROVAL_BINDING_MISMATCH"):
        bind(context, approval)


def test_approval_cannot_transfer_to_new_observation_at_same_revision(context):
    approval = approve(context)
    receipt = {**context["receipt"], "source": "new-independent-observation"}
    preview = context["store"].store_preview(context["manifest"], receipt)["preview_sha256"]
    assert preview != context["preview"]
    with pytest.raises(DraftStop, match="APPROVAL_BINDING_MISMATCH"):
        bind({**context, "preview": preview}, approval)


def test_approval_rechecks_saved_draft_integrity_and_rolls_back(context):
    context["store"].db.execute("UPDATE drafts SET semantic_sha=?", ("f" * 64,))
    context["store"].db.commit()
    with pytest.raises(DraftStop, match="PERSISTED_DRAFT_CORRUPT"):
        approve(context)
    assert context["store"].db.execute("SELECT count(*) FROM preview_approvals").fetchone() == (0,)
    assert not context["store"].db.in_transaction


def test_concurrent_approval_registration_is_idempotent(context):
    barrier = Barrier(2)

    def worker():
        store = DraftStore(context["path"])
        try:
            barrier.wait(timeout=5)
            return approve({**context, "store": store})
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        results = [f.result(timeout=10) for f in futures]
    assert results[0]["approval_sha256"] == results[1]["approval_sha256"]
    assert sorted(r["reused"] for r in results) == [False, True]


def test_extra_or_duplicated_review_targets_are_rejected(context):
    context["review"]["requested_targets"] *= 2
    with pytest.raises(DraftStop, match="APPROVAL_TARGET_MISMATCH"):
        approve(context)


def test_only_one_reviewed_version_can_ever_bind_to_request(context):
    first = approve(context)
    newer = revised_preview(context)
    second = approve(newer)
    bind(newer, second)
    with pytest.raises(DraftStop, match="REQUEST_EXECUTION_ALREADY_BOUND"):
        bind(context, first)
    with pytest.raises(DraftStop, match="REQUEST_EXECUTION_ALREADY_BOUND"):
        approve(context)
    assert bind(newer, second)["reused"] is True


@pytest.mark.parametrize("different", [False, True])
def test_concurrent_connections_bind_once_or_reject_different_review(context, different):
    first = approve(context)
    newer = revised_preview(context) if different else context
    second = approve(newer)
    barrier = Barrier(2)

    def worker(ctx, approval):
        store = DraftStore(ctx["path"])
        try:
            barrier.wait(timeout=5)
            try:
                return bind({**ctx, "store": store}, approval)
            except DraftStop as exc:
                return exc.code
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, context, first), pool.submit(worker, newer, second)]
        results = [f.result(timeout=10) for f in futures]
    if different:
        assert sum(isinstance(r, dict) for r in results) == 1
        assert "REQUEST_EXECUTION_ALREADY_BOUND" in results
    else:
        assert sorted(r["reused"] for r in results) == [False, True]
    assert context["store"].db.execute("SELECT count(*) FROM execution_bindings").fetchone() == (1,)


def test_bound_changeset_uses_real_ledger_and_reads_back_on_resume(context, tmp_path):
    execution = bind(context, approve(context))
    manifest = execution["manifest"]
    for _ in range(2):
        ledger = Ledger(tmp_path / "execution.sqlite3")
        try:
            result = run_changeset(
                manifest, {"plan.workout.patch": context["provider"]}, ledger,
                execute=True, reviewed_revision=REVISION, approval_scope=SCOPE)
            assert result["results"][0]["state"] == "DONE_VERIFIED"
        finally:
            ledger.close()
    assert context["provider"].writes == 1


def test_recording_approval_never_upgrades_original_preview(context):
    approve(context)
    ledger = Ledger(":memory:")
    try:
        with pytest.raises(ChangeStop, match="PREVIEW_DRAFT_NOT_APPROVED"):
            run_changeset(context["manifest"], {}, ledger, execute=True,
                          reviewed_revision=REVISION, approval_scope=SCOPE)
    finally:
        ledger.close()


def test_denial_persists_across_bound_execution_resume(context, tmp_path):
    manifest = bind(context, approve(context))["manifest"]
    context["provider"].denied = True
    ledger = Ledger(tmp_path / "execution.sqlite3")
    try:
        for _ in range(2):
            result = run_changeset(manifest, {"plan.workout.patch": context["provider"]},
                                   ledger, execute=True, reviewed_revision=REVISION,
                                   approval_scope=SCOPE)
            assert result["results"][0]["state"] == "BLOCKED_SECURITY"
        assert context["provider"].writes == 1
    finally:
        ledger.close()
