"""Actual Prefect runtime and signed identity; synthetic issuer/provider only.

No cloud Prefect API, TrainingPeaks credentials, deployments or schedules.
"""
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from prefect import flow, task
from prefect.context import get_run_context
from prefect.settings import (
    PREFECT_API_KEY, PREFECT_API_URL, PREFECT_HOME, PREFECT_SERVER_ANALYTICS_ENABLED, temporary_settings,
)
from prefect.testing.utilities import prefect_test_harness

from scripts.ironman_jobs import ironman_operation_contracts as contracts
from scripts.ironman_jobs import ironman_unified_prefect_flow as pipeline
from scripts.ironman_jobs.ironman_authorization import (
    ACTIONS, HostReviewAuthority, SignedIdentityVerifier, current_invocation_id,
    assertion_path_for_invocation,
)
from scripts.ironman_jobs.ironman_dynamic_request_store import DraftStop, DraftStore
from scripts.ironman_jobs.ironman_unified_changeset_engine import ChangeStop, digest
from test_ironman_authorization import signed
from test_ironman_worker_recovery import orphan


@pytest.fixture(scope="module")
def prefect_runtime(tmp_path_factory):
    # Always isolate this module even when invoked directly by a developer
    # who has a production PREFECT_API_URL/profile configured.
    with temporary_settings({PREFECT_API_KEY: None, PREFECT_API_URL: None,
                             PREFECT_HOME: tmp_path_factory.mktemp("prefect-runtime"),
                             PREFECT_SERVER_ANALYTICS_ENABLED: False}):
        with prefect_test_harness():
            yield


def test_flow_and_task_share_authenticated_flow_origin(prefect_runtime):
    @task(persist_result=False)
    def identity_inside_task():
        context = get_run_context()
        assert context.task_run.flow_run_id is not None
        return current_invocation_id(), str(context.task_run.id)

    @flow(persist_result=False)
    def identity_flow():
        own = current_invocation_id()
        task_origin, task_id = identity_inside_task()
        assert task_id != own
        return own, task_origin

    own, task_origin = identity_flow()
    assert own == task_origin


def test_task_outside_flow_cannot_impersonate_flow_identity(prefect_runtime):
    @task(persist_result=False)
    def standalone_task():
        with pytest.raises(PermissionError):
            current_invocation_id()
        return True

    assert standalone_task() is True


class Provider:
    def __init__(self):
        self.value, self.reads, self.writes = {"title": "before"}, 0, 0

    def read(self, _):
        self.reads += 1
        return dict(self.value)

    def apply(self, _):
        self.writes += 1
        raise AssertionError("NO_PROVIDER_WRITE_IN_RUNTIME_QA")


@pytest.fixture
def runtime_operator(tmp_path, monkeypatch):
    key = ed25519.Ed25519PrivateKey.generate()
    config = {"issuer": "https://synthetic-issuer.invalid", "audience": "ironman-runtime-test",
              "required_scope": "ironman:operator", "administrators": ["runtime-admin"],
              "keys": {"test-key": {"algorithm": "EdDSA", "public_key_pem": key.public_key().public_bytes(
                  serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()}}}
    config_path, assertion_directory = tmp_path / "trust.json", tmp_path / "assertions"
    assertion_directory.mkdir(mode=0o700)
    config_path.write_text(json.dumps(config))
    config_path.chmod(0o600)
    store_path, ledger_path = tmp_path / "drafts.sqlite3", tmp_path / "execution.sqlite3"
    monkeypatch.setenv("IRONMAN_REVIEW_TRUST_CONFIG", str(config_path))
    monkeypatch.delenv("IRONMAN_REVIEW_ASSERTION_FILE", raising=False)
    monkeypatch.setenv("IRONMAN_REVIEW_ASSERTION_DIRECTORY", str(assertion_directory))
    monkeypatch.setenv("IRONMAN_OPERATION_DRAFT_STORE", str(store_path))
    monkeypatch.setenv("IRONMAN_OPERATION_EXECUTION_LEDGER", str(ledger_path))
    provider = Provider()
    monkeypatch.setattr(pipeline, "create_read_registry", lambda _: {"plan.workout.patch": provider})
    target = {"kind": "plan.workout.patch", "target": {"provider": "trainingpeaks", "owner_id": 2116886,
              "container_kind": "training_plan", "container_id": 501, "resource_id": 31}}
    state = dict(store=store_path, ledger=ledger_path, provider=provider, target=target,
                 invocations=[], grant=None, delegate=True)
    original_factory = contracts.get_review_authorizer

    def write_assertion(claims):
        token = signed(key, claims)
        assertion_path = assertion_path_for_invocation(assertion_directory, claims["run_id"])
        assertion_path.write_text(token)
        assertion_path.chmod(0o600)
        return token

    def issuer_handoff():
        # The only simulated boundary is the upstream issuer/launcher handing
        # over a private assertion AFTER Prefect assigns the actual flow ID.
        # Verification, grant store, audit and invocation lookup are not mocked.
        run_id = current_invocation_id()
        state["invocations"].append(run_id)
        if not state["delegate"]:
            return original_factory()
        now = int(time.time())
        claims = {"iss": config["issuer"], "aud": config["audience"], "sub": "runtime-user",
                  "jti": "runtime-user-" + run_id, "iat": now - 1, "nbf": now - 1,
                  "exp": now + 600, "scope": "ironman:operator", "run_id": run_id}
        if state["grant"] is None:
            write_assertion({**claims, "sub": "runtime-admin", "jti": "runtime-admin-" + run_id})
            verifier = SignedIdentityVerifier(config)
            admin_service = HostReviewAuthority(store_path, verifier, lambda: assertion_path_for_invocation(
                assertion_directory, current_invocation_id()).read_text())
            user = verifier.verify(signed(key, claims))
            state["grant"] = admin_service.grant(user, state["request_id"], state["preview_sha256"],
                                                    approval_scope="approved:runtime-review",
                                                    actions=sorted(ACTIONS), expires_at=now + 500)
        write_assertion(claims)
        if state.get("handoff_barrier") is not None:
            state["handoff_barrier"].wait(timeout=10)
        return original_factory()

    monkeypatch.setattr(pipeline, "get_review_authorizer", issuer_handoff)
    monkeypatch.setattr(contracts, "get_review_authorizer", issuer_handoff)

    def invoke(mode, payload):
        return pipeline.unified_changeset_flow(payload, str(ledger_path), mode=mode, requested_targets=[target])

    state["invoke"] = invoke
    return state


def prepare_preview(state):
    prepared = state["invoke"]("prepare", {"schema": "IRONMAN_OPERATION_INPUT_V1",
        "request_key": "real-prefect-operator-lifecycle", "items": [{
            "id": "patch01", "kind": "plan.workout.patch", "target": state["target"]["target"],
            "depends_on": [], "before_sha256": digest({"title": "before"}),
            "payload": {"desired": {"title": "after"}},
        }]})
    preview = state["invoke"]("preview_draft", {"schema": "IRONMAN_DRAFT_PREVIEW_INPUT_V1",
        "request_id": prepared["request_id"], "after_images": {"patch01": {"title": "after"}},
        "pinned_revision": "a" * 40})
    state.update(request_id=prepared["request_id"], preview_sha256=preview["preview_sha256"])
    return {"schema": "IRONMAN_REVIEW_INPUT_V1", "request_id": state["request_id"],
            "preview_sha256": state["preview_sha256"], "reviewed_revision": "a" * 40,
            "approval_scope": "approved:runtime-review"}


def test_complete_control_lifecycle_on_actual_prefect(prefect_runtime, runtime_operator):
    state = runtime_operator
    request = prepare_preview(state)
    approval = state["invoke"]("approve_preview", request)
    request["approval_sha256"] = approval["approval_sha256"]
    bound = state["invoke"]("bind_execution", request)
    assert bound["state"] == "EXECUTION_BOUND"
    assert state["invoke"]("bind_execution", request)["reused"] is True
    reads = state["provider"].reads
    revoked = state["invoke"]("revoke_approval", request)
    assert revoked["state"] == "APPROVAL_REVOKED"
    with pytest.raises(DraftStop, match="APPROVAL_REVOKED"):
        state["invoke"]("bind_execution", request)
    assert state["provider"].reads == reads and state["provider"].writes == 0
    assert not state["ledger"].exists()
    assert len(set(state["invocations"])) >= 5
    store = DraftStore(state["store"])
    try:
        actors = store.db.execute("SELECT DISTINCT subject FROM authority_audit").fetchall()
        assert ("runtime-user",) in actors and ("runtime-admin",) in actors
    finally:
        store.close()


def test_signed_authority_works_in_prefect_child_task(prefect_runtime, runtime_operator):
    state = runtime_operator
    request = prepare_preview(state)

    @task(persist_result=False)
    def approve_in_task():
        # Exercise the same authorization/control logic in a real task context;
        # do not replace signature verification or the runtime identity source.
        return pipeline.unified_changeset_flow.fn(
            request, str(state["ledger"]), mode="approve_preview", requested_targets=[state["target"]])

    @flow(persist_result=False)
    def delegated_flow():
        return approve_in_task()

    assert delegated_flow()["state"] == "APPROVAL_RECORDED"
    assert state["provider"].writes == 0 and not state["ledger"].exists()


def test_previous_invocation_assertion_is_refused_by_actual_flow(prefect_runtime, runtime_operator):
    state = runtime_operator
    request = prepare_preview(state)
    approval = state["invoke"]("approve_preview", request)
    state["delegate"] = False  # Host does NOT issue a new assertion for next flow.
    with pytest.raises(ChangeStop, match="REVIEW_AUTHORIZATION_DENIED"):
        state["invoke"]("bind_execution", {**request, "approval_sha256": approval["approval_sha256"]})
    assert not state["ledger"].exists() and state["provider"].writes == 0


def test_concurrent_real_flows_keep_separate_issuer_assertions(prefect_runtime, runtime_operator):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    state = runtime_operator
    request = prepare_preview(state)
    approval = state["invoke"]("approve_preview", request)
    request["approval_sha256"] = approval["approval_sha256"]
    # Both signed identities are installed before either factory returns. A
    # shared file would leave one flow holding the other flow's assertion.
    state["handoff_barrier"] = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(state["invoke"], "bind_execution", request) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert {row["state"] for row in results} == {"EXECUTION_BOUND"}
    assert sorted(row["reused"] for row in results) == [False, True]
    assert len(set(state["invocations"][-2:])) == 2
    assert state["provider"].writes == 0 and not state["ledger"].exists()


def test_orphan_recovery_on_actual_prefect_does_not_reactivate_approval(prefect_runtime, runtime_operator):
    state = runtime_operator
    request = prepare_preview(state)
    approval = state["invoke"]("approve_preview", request)
    request["approval_sha256"] = approval["approval_sha256"]
    bound = state["invoke"]("bind_execution", request)
    state["invoke"]("revoke_approval", request)
    owner = orphan(state["ledger"], bound["manifest"])
    state["provider"].value = {"title": "after"}
    recovered = state["invoke"]("recover_worker", {**request, "schema": "IRONMAN_RECOVERY_INPUT_V1", "worker_owner": owner})
    assert recovered["state"] == "WORKER_RECOVERED" and recovered["provider_writes"] == 0
    assert recovered["reconciliation_required"] is False and state["provider"].writes == 0
    with pytest.raises(DraftStop, match="APPROVAL_REVOKED"):
        state["invoke"]("bind_execution", request)


def test_actual_prefect_recovery_persists_new_provider_denial(prefect_runtime, runtime_operator, monkeypatch):
    from scripts.ironman_jobs.ironman_unified_changeset_engine import Ledger, SecurityDenied

    state = runtime_operator
    request = prepare_preview(state)
    approval = state["invoke"]("approve_preview", request)
    request["approval_sha256"] = approval["approval_sha256"]
    bound = state["invoke"]("bind_execution", request)
    owner = orphan(state["ledger"], bound["manifest"])
    original_read = state["provider"].read

    def denied(_):
        state["provider"].reads += 1
        raise SecurityDenied("SYNTHETIC_PROVIDER_DENIED")

    monkeypatch.setattr(state["provider"], "read", denied)
    recovery = {**request, "schema": "IRONMAN_RECOVERY_INPUT_V1", "worker_owner": owner}
    result = state["invoke"]("recover_worker", recovery)
    assert result["results"][0]["state"] == "BLOCKED_SECURITY"
    assert result["provider_writes"] == 0 and result["reconciliation_required"] is True
    reads = state["provider"].reads
    monkeypatch.setattr(state["provider"], "read", original_read)
    assert state["invoke"]("recover_worker", recovery)["reused"] is True
    assert state["provider"].reads == reads and state["provider"].writes == 0
    ledger = Ledger(state["ledger"])
    try:
        assert ledger.status(state["request_id"], "patch01") == "BLOCKED_SECURITY"
        assert ledger.db.execute("SELECT count(*) FROM resource_claims").fetchone() == (1,)
    finally:
        ledger.close()
