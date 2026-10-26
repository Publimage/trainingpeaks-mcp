"""Real DraftStore/Changeset integration; synthetic provider, no network."""
import copy
import importlib.util
import sys
import types
from pathlib import Path
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
        receipt = run_changeset(manifest, {"plan.workout.patch": provider}, ledger, authorize_execution=lambda *_: True)
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
                execute=True, reviewed_revision=REVISION, approval_scope=SCOPE, authorize_execution=lambda *_: True)
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
                          reviewed_revision=REVISION, approval_scope=SCOPE, authorize_execution=lambda *_: True)
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
                                   approval_scope=SCOPE, authorize_execution=lambda *_: True)
            assert result["results"][0]["state"] == "BLOCKED_SECURITY"
        assert context["provider"].writes == 1
    finally:
        ledger.close()


@pytest.fixture
def real_flow(monkeypatch):
    """Only Prefect scheduling and provider transport are stubbed here."""
    prefect = types.ModuleType("prefect")

    def decorator(**kwargs):
        def wrap(fn):
            fn.fn = fn
            return fn
        return wrap

    prefect.flow = prefect.task = decorator
    reads = types.ModuleType("scripts.ironman_jobs.ironman_unified_trainingpeaks_reads")

    def forbidden(*args, **kwargs):
        raise AssertionError("CONTROL_FLOW_MUST_NOT_OPEN_PROVIDER")

    reads.create_read_registry = forbidden
    monkeypatch.setitem(sys.modules, "prefect", prefect)
    monkeypatch.setitem(sys.modules, reads.__name__, reads)
    path = Path(__file__).parents[1] / "scripts/ironman_jobs/ironman_unified_prefect_flow.py"
    spec = importlib.util.spec_from_file_location("approval_flow_integration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Authority:
    """Test-only stand-in for the authenticated host's current grant service."""
    def __init__(self):
        self.currently_allowed = True
        self.calls = []

    def authorize(self, command):
        self.calls.append(copy.deepcopy(command))
        return self.currently_allowed


def control(ctx, approval=None):
    result = {"schema": "IRONMAN_REVIEW_INPUT_V1", "request_id": ctx["draft"]["request_id"],
              "preview_sha256": ctx["preview"], "reviewed_revision": REVISION,
              "approval_scope": SCOPE}
    if approval:
        result["approval_sha256"] = approval["approval_sha256"]
    return result


def call_flow(module, ctx, tmp_path, mode, approval=None):
    return module.unified_changeset_flow.fn(
        control(ctx, approval), str(tmp_path / "must-not-open.sqlite3"), mode=mode,
        requested_targets=ctx["review"]["requested_targets"])


def test_flow_default_denies_review_without_trusted_authority(context, real_flow, monkeypatch, tmp_path):
    monkeypatch.setenv("IRONMAN_OPERATION_DRAFT_STORE", str(context["path"]))
    with pytest.raises(ChangeStop, match="REVIEW_AUTHORIZATION_DENIED"):
        call_flow(real_flow, context, tmp_path, "approve_preview")
    assert context["store"].db.execute("SELECT count(*) FROM preview_approvals").fetchone() == (0,)


def test_real_store_flow_approve_bind_revoke_resume_and_reapproval(context, real_flow, monkeypatch, tmp_path):
    monkeypatch.setenv("IRONMAN_OPERATION_DRAFT_STORE", str(context["path"]))
    authority = Authority()
    monkeypatch.setattr(real_flow, "get_review_authorizer", lambda: authority)
    approval = call_flow(real_flow, context, tmp_path, "approve_preview")
    assert call_flow(real_flow, context, tmp_path, "approve_preview")["reused"] is True
    bound = call_flow(real_flow, context, tmp_path, "bind_execution", approval)
    assert bound["state"] == "EXECUTION_BOUND"
    assert bound["publication_enabled"] is False
    assert call_flow(real_flow, context, tmp_path, "bind_execution", approval)["reused"] is True
    revoked = call_flow(real_flow, context, tmp_path, "revoke_approval", approval)
    assert revoked["state"] == "APPROVAL_REVOKED"
    assert call_flow(real_flow, context, tmp_path, "revoke_approval", approval)["reused"] is True
    for mode, token in (("bind_execution", approval), ("approve_preview", None)):
        with pytest.raises(DraftStop, match="APPROVAL_REVOKED"):
            call_flow(real_flow, context, tmp_path, mode, token)
    assert authority.calls[0]["manifest"] == context["manifest"]
    assert authority.calls[0]["action"] == "approve_preview"
    assert context["provider"].writes == 0
    assert not (tmp_path / "must-not-open.sqlite3").exists()


@pytest.mark.parametrize("mode", ["approve_preview", "bind_execution", "revoke_approval"])
def test_authority_current_denial_prevents_all_control_mutations(context, real_flow, monkeypatch, tmp_path, mode):
    approval = approve(context)
    monkeypatch.setenv("IRONMAN_OPERATION_DRAFT_STORE", str(context["path"]))
    authority = Authority()
    authority.currently_allowed = False
    monkeypatch.setattr(real_flow, "get_review_authorizer", lambda: authority)
    with pytest.raises(ChangeStop, match="REVIEW_AUTHORIZATION_DENIED"):
        call_flow(real_flow, context, tmp_path, mode, None if mode == "approve_preview" else approval)
    assert context["store"].db.execute("SELECT count(*) FROM execution_bindings").fetchone() == (0,)
    assert context["store"].db.execute("SELECT count(*) FROM approval_revocations").fetchone() == (0,)


def test_revocation_survives_reopen_and_cannot_be_undone_by_retry(context):
    approval = approve(context)
    context["store"].revoke_approval(context["draft"]["request_id"], context["preview"],
                                       approval["approval_sha256"], **context["review"])
    context["store"].close()
    context["store"] = DraftStore(context["path"])
    with pytest.raises(DraftStop, match="APPROVAL_REVOKED"):
        bind(context, approval)
    with pytest.raises(DraftStop, match="APPROVAL_REVOKED"):
        approve(context)


def test_revoke_and_bind_race_is_serialized(context):
    approval = approve(context)
    barrier = Barrier(2)

    def worker(revoke):
        store = DraftStore(context["path"])
        ctx = {**context, "store": store}
        try:
            barrier.wait(timeout=5)
            try:
                if revoke:
                    return store.revoke_approval(context["draft"]["request_id"], context["preview"],
                                                   approval["approval_sha256"], **context["review"])
                return bind(ctx, approval)
            except DraftStop as exc:
                return exc.code
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, revoke) for revoke in (True, False)]
        results = [f.result(timeout=10) for f in futures]
    assert results[0]["state"] == "APPROVAL_REVOKED"
    assert results[1] == "APPROVAL_REVOKED" or results[1]["state"] == "EXECUTION_BOUND"
    with pytest.raises(DraftStop, match="APPROVAL_REVOKED"):
        bind(context, approval)


def test_shared_target_contract_handles_same_resource_chain(context, real_flow):
    from scripts.ironman_jobs.ironman_operation_contracts import require_target_binding
    manifest = copy.deepcopy(context["manifest"])
    manifest["changes"].append({**manifest["changes"][0], "id": "patch02", "depends_on": ["patch01"]})
    selectors = context["review"]["requested_targets"]
    require_target_binding(manifest, selectors)
    real_flow.require_requested_targets(manifest, selectors)
    # Approval uses the SAME function rather than requiring duplicate selectors.
    draft = prepare_draft([{
        key: item[key] for key in ("id", "kind", "target", "payload", "before_sha256", "depends_on")
    } for item in manifest["changes"]], request_key="same-resource-chain")
    context["store"].store(draft)
    manifest["request_id"] = draft["request_id"]
    manifest["approval_scope"] = "PREVIEW_ONLY:" + draft["request_id"]
    receipt = {**context["receipt"], "request_id": draft["request_id"],
               "manifest_sha256": digest(manifest), "results": [
                   {"id": item["id"], "state": "PREFLIGHT_PASS"} for item in manifest["changes"]]}
    preview = context["store"].store_preview(manifest, receipt)["preview_sha256"]
    assert context["store"].record_approval(draft["request_id"], preview,
                                             **context["review"])["state"] == "APPROVAL_RECORDED"


def test_bound_guard_rechecks_revocation_between_dependent_mutations(context, monkeypatch, tmp_path):
    from scripts.ironman_jobs import ironman_operation_contracts as contracts
    authority = Authority()
    monkeypatch.setattr(contracts, "get_review_authorizer", lambda: authority)
    first = context["draft"]["items"][0]
    second = {**first, "id": "patch02", "depends_on": ["patch01"],
              "before_sha256": digest({"title": "after"}),
              "payload": {"desired": {"title": "final"}}}
    draft = prepare_draft([{k: v for k, v in row.items() if k != "adapter_readiness"}
                           for row in (first, second)],
                          request_key="revocation-between-writes")
    store = context["store"]
    store.store(draft)
    manifest = compile_preview_changeset(draft, {"patch01": {"title": "after"},
                                                "patch02": {"title": "final"}},
                                         pinned_revision=REVISION)["manifest"]
    preview_ledger = Ledger(":memory:")
    try:
        receipt = run_changeset(manifest, {"plan.workout.patch": context["provider"]}, preview_ledger)
    finally:
        preview_ledger.close()
    receipt.update(provider_writes=0, publication_enabled=False)
    preview = store.store_preview(manifest, receipt)["preview_sha256"]
    approval = store.record_approval(draft["request_id"], preview, **context["review"])
    bound = store.bind_execution(draft["request_id"], preview, approval["approval_sha256"], **context["review"])
    guard = contracts.BoundExecutionAuthorization(context["path"], draft["request_id"], preview,
                                                  approval["approval_sha256"], **context["review"])
    provider = context["provider"]
    original_apply = provider.apply

    def apply_and_revoke(spec):
        original_apply(spec)
        store.revoke_approval(draft["request_id"], preview, approval["approval_sha256"], **context["review"])

    provider.apply = apply_and_revoke
    ledger = Ledger(tmp_path / "guarded-execution.sqlite3")
    try:
        result = run_changeset(bound["manifest"], {"plan.workout.patch": provider}, ledger,
                                execute=True, reviewed_revision=REVISION, approval_scope=SCOPE,
                                authorize_execution=guard)
        assert [row["state"] for row in result["results"]] == ["DONE_VERIFIED", "BLOCKED_SECURITY"]
        assert provider.writes == 1
        with pytest.raises(SecurityDenied, match="EXECUTION_AUTHORIZATION_DENIED"):
            run_changeset(bound["manifest"], {"plan.workout.patch": provider}, ledger,
                          execute=True, reviewed_revision=REVISION, approval_scope=SCOPE,
                          authorize_execution=guard)
    finally:
        ledger.close()


def test_execution_requires_independent_authority_even_with_matching_scope(context, tmp_path):
    execution = bind(context, approve(context))
    ledger = Ledger(tmp_path / "execution.sqlite3")
    try:
        with pytest.raises(ChangeStop, match="EXECUTION_AUTHORITY_REQUIRED"):
            run_changeset(execution["manifest"], {"plan.workout.patch": context["provider"]},
                          ledger, execute=True, reviewed_revision=REVISION, approval_scope=SCOPE)
        assert context["provider"].writes == 0
        assert ledger.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (0,)
    finally:
        ledger.close()


@pytest.mark.parametrize("failure", ["unconfigured", "current-denial", "changed-manifest"])
def test_bound_guard_fails_closed_without_reserving_execution(context, monkeypatch, failure):
    from scripts.ironman_jobs import ironman_operation_contracts as contracts
    approval = approve(context)
    guard = contracts.BoundExecutionAuthorization(context["path"], context["draft"]["request_id"],
                                                  context["preview"], approval["approval_sha256"],
                                                  **context["review"])
    manifest = {**context["manifest"], "approval_scope": SCOPE}
    if failure != "unconfigured":
        authority = Authority()
        authority.currently_allowed = failure != "current-denial"
        monkeypatch.setattr(contracts, "get_review_authorizer", lambda: authority)
    if failure == "changed-manifest":
        manifest = copy.deepcopy(manifest)
        manifest["changes"][0]["target"]["resource_id"] = 999
    with pytest.raises(PermissionError):
        guard(manifest, None)
    assert context["store"].db.execute("SELECT count(*) FROM execution_bindings").fetchone() == (0,)
