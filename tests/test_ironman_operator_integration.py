"""Real MCP protocol -> Prefect -> durable stores -> reviewed adapter.

Only ingress/issuer signing and the provider transport are synthetic. No
production binding, service, deployment, identity or credential is installed.
"""
import json
import time
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from mcp import Client

from tp_mcp.operator_runtime import bind_operator_runtime, current_bindings
from tp_mcp.server import server
from scripts.ironman_jobs.ironman_authorization import (
    ACTIONS, SignedIdentityVerifier, assertion_path_for_invocation,
    authority_from_host, current_invocation_id,
)
from scripts.ironman_jobs.ironman_dynamic_request_store import DraftStore
from scripts.ironman_jobs.ironman_unified_changeset_engine import Ledger, digest
from scripts.ironman_jobs.ironman_unified_plan_workout_adapter import ReviewedClassicPlanPatchAdapter
from scripts.ironman_jobs.ironman_unified_prefect_flow import compose_operator_runtime
from test_ironman_authorization import signed
from test_ironman_prefect_runtime import prefect_runtime
from test_ironman_unified_plan_workout_adapter import FakePlanProvider, workout
from test_ironman_unified_trainingpeaks_reads import Response

KIND = "plan.workout.patch"
REVISION = "b" * 40
SCOPE = "approved:synthetic-mcp-integration"


class Gateway(FakePlanProvider):
    def __init__(self):
        super().__init__({(501, 101): workout(101)})
        self.unreadable, self.lose_response = False, False
        self.reads = 0

    def read(self, change):
        self.reads += 1
        if self.unreadable:
            raise ConnectionError("SYNTHETIC_PROVIDER_UNAVAILABLE")
        return super().read(change)

    def put_one(self, plan_id, workout_id, desired):
        super().put_one(plan_id, workout_id, desired)
        if self.lose_response:
            self.unreadable = True
            raise TimeoutError("SYNTHETIC_RESPONSE_LOST_AFTER_COMMIT")


@pytest.fixture
def host(tmp_path, monkeypatch):
    key = ed25519.Ed25519PrivateKey.generate()
    config = {"issuer": "https://synthetic-issuer.invalid", "audience": "integration-only",
              "required_scope": "ironman:operator", "administrators": ["test-admin"],
              "keys": {"test-key": {"algorithm": "EdDSA", "public_key_pem": key.public_key().public_bytes(
                  serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()}}}
    trust, directory, store = tmp_path / "trust.json", tmp_path / "assertions", tmp_path / "drafts.sqlite3"
    trust.write_text(json.dumps(config))
    trust.chmod(0o600)
    directory.mkdir(mode=0o700)
    monkeypatch.setenv("IRONMAN_REVIEW_TRUST_CONFIG", str(trust))
    monkeypatch.setenv("IRONMAN_REVIEW_ASSERTION_DIRECTORY", str(directory))
    monkeypatch.delenv("IRONMAN_REVIEW_ASSERTION_FILE", raising=False)
    monkeypatch.setenv("IRONMAN_OPERATION_DRAFT_STORE", str(store))
    ledger = tmp_path / "execution.sqlite3"
    from scripts.ironman_jobs.ironman_unified_changeset_engine import Ledger
    Ledger(ledger).close()  # Explicit trusted host initialization, never request recovery.
    monkeypatch.setenv("IRONMAN_OPERATION_EXECUTION_LEDGER", str(ledger))
    verifier = SignedIdentityVerifier(config)
    state = {"proof": None, "grants": set(), "origins": [], "admissions": [], "key": key,
             "store": store, "ledger": ledger, "directory": directory}

    def claims(origin, subject="test-user"):
        now = int(time.time())
        return {"iss": config["issuer"], "aud": config["audience"], "scope": config["required_scope"],
                "sub": subject, "jti": subject + ":" + origin, "iat": now - 1, "nbf": now - 1,
                "exp": now + 600, "run_id": origin}

    def admit(command):
        # Synthetic trusted transport delegation is OUTSIDE the MCP payload;
        # a real signature binds this admission to the exact command digest.
        principal = verifier.verify(state["proof"])
        allowed = principal.subject == "test-user" and principal.invocation_id == digest(command)
        if allowed:
            state["admissions"].append(digest(command))
        return allowed

    def launch(mode, payload):
        origin = current_invocation_id()  # Actual Prefect context, not a stub.
        state["origins"].append(origin)
        path = assertion_path_for_invocation(directory, origin)
        def install(token):
            pending = path.with_suffix(".pending")
            pending.write_text(token)
            pending.chmod(0o600)
            pending.replace(path)
        if mode in {"approve_preview", "bind_execution", "execute_bound", "revoke_approval", "recover_worker"}:
            selector = (payload["request_id"], payload["preview_sha256"])
            if selector not in state["grants"]:
                install(signed(key, claims(origin, "test-admin")))
                user = verifier.verify(signed(key, claims(origin)))
                authority_from_host().grant(user, *selector, approval_scope=payload["approval_scope"],
                                           actions=sorted(ACTIONS), expires_at=int(time.time()) + 500)
                state["grants"].add(selector)
        install(signed(key, claims(origin)))

    provider = Gateway()
    class SyntheticHTTP:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            return False
        async def _get_user_data(self):
            return {"personId": 2116886}
        async def get(self, route):
            state.setdefault("http_reads", []).append(route)
            if route == "/plans/v1/plans/501":
                return Response({"planId": 501, "ownerPersonId": 2116886, "planPersonId": 600,
                                 "startDate": "2027-03-29", "weekCount": 1})
            if route.startswith("/plans/v1/plans/501/workouts/"):
                return Response([provider.read({"target": {"container_id": 501, "resource_id": 101}})])
            raise AssertionError("UNEXPECTED_SYNTHETIC_HTTP_ROUTE")
    # Replace only the provider HTTP boundary. Owner/container discovery,
    # membership validation and the native read adapter remain real code.
    monkeypatch.setattr("tp_mcp.client.TPClient", SyntheticHTTP)
    adapter = ReviewedClassicPlanPatchAdapter(put_one=provider.put_one)
    state.update(provider=provider, claims=claims,
        bindings=compose_operator_runtime(ledger_path=str(ledger), authorize_request=admit,
                                  read_transport="local", writers={KIND: adapter},
                                  enabled_write_kinds=frozenset({KIND}), on_flow_start=launch))
    return state


def command(mode, manifest):
    return {"mode": mode, "manifest": manifest, "requested_targets": [{"kind": KIND,
        "target": {"provider": "trainingpeaks", "owner_id": 2116886,
                   "container_kind": "training_plan", "container_id": 501, "resource_id": 101}}]}


async def request(client, host, mode, manifest, *, expect_error=False):
    value = command(mode, manifest)
    host["proof"] = signed(host["key"], host["claims"](digest(value)))
    result = await client.call_tool("tp_ironman_request", value)
    payload = json.loads(result.content[0].text)
    if not expect_error:
        assert not payload.get("isError"), payload
    return payload


async def reviewed_request(client, host):
    before = workout(101)
    after = {**before, "title": "Reviewed synthetic title"}
    target = command("prepare", {})["requested_targets"][0]["target"]
    draft = {"schema": "IRONMAN_OPERATION_INPUT_V1", "request_key": "mcp-complete-request",
             "items": [{"id": "patch01", "kind": KIND, "target": target, "depends_on": [],
                        "before_sha256": digest(before), "payload": {"desired": after, "fields": ["title"]}}]}
    prepared = await request(client, host, "prepare", draft)
    again = await request(client, host, "prepare", draft)
    assert prepared["request_id"] == again["request_id"]
    preview = await request(client, host, "preview_draft", {"schema": "IRONMAN_DRAFT_PREVIEW_INPUT_V1",
        "request_id": prepared["request_id"], "after_images": {"patch01": after}, "pinned_revision": REVISION})
    review = {"schema": "IRONMAN_REVIEW_INPUT_V1", "request_id": prepared["request_id"],
              "preview_sha256": preview["preview_sha256"], "reviewed_revision": REVISION, "approval_scope": SCOPE}
    approval = await request(client, host, "approve_preview", review)
    review["approval_sha256"] = approval["approval_sha256"]
    bound = await request(client, host, "bind_execution", review)
    assert bound["state"] == "EXECUTION_BOUND"
    return review


@pytest.mark.parametrize("lose_response", [False, True])
async def test_complete_mcp_prefect_lifecycle_and_safe_retry(prefect_runtime, host, lose_response):
    with bind_operator_runtime(host["bindings"]):
        async with Client(server) as client:
            review = await reviewed_request(client, host)
            host["provider"].lose_response = lose_response
            first = await request(client, host, "execute_bound", review)
            assert first["results"][0]["state"] == ("UNKNOWN_NEEDS_READBACK" if lose_response else "DONE_VERIFIED")
            host["provider"].unreadable = False
            again = await request(client, host, "execute_bound", review)
            assert again["request_state"] == "WORK_COMPLETE"
            assert host["provider"].writes == [(501, 101)]  # No second PUT.
            ledger = Ledger(host["ledger"])
            store = DraftStore(host["store"])
            try:
                assert ledger.status(review["request_id"], "patch01") == "DONE_VERIFIED"
                assert ledger.db.execute("SELECT count(*) FROM resource_claims").fetchone() == (0,)
                assert ledger.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (0,)
                assert store.get_preview(review["request_id"], review["preview_sha256"])
                assert store.db.execute("SELECT count(*) FROM execution_bindings").fetchone() == (1,)
            finally:
                ledger.close()
                store.close()
            revoked = await request(client, host, "revoke_approval", review)
            assert revoked["state"] == "APPROVAL_REVOKED"
            denied = await request(client, host, "execute_bound", review, expect_error=True)
            assert denied["isError"] and host["provider"].writes == [(501, 101)]
    assert current_bindings() is None
    assert "/plans/v1/plans/501" in host["http_reads"]
    assert len(host["admissions"]) >= 8 and len(set(host["origins"])) >= 8


async def test_mcp_default_deny_and_untrusted_payload():
    async with Client(server) as client:
        result = await client.call_tool("tp_ironman_request", command("prepare", {}))
        assert json.loads(result.content[0].text)["error_code"] == "OPERATOR_REQUEST_DENIED"
        bad = {**command("prepare", {}), "principal": "admin"}
        result = await client.call_tool("tp_ironman_request", bad)
        assert json.loads(result.content[0].text)["error_code"] == "OPERATOR_REQUEST_SHAPE"


@pytest.mark.parametrize("missing", ["gate", "writer"])
async def test_mcp_admission_and_writer_capability_are_independent(prefect_runtime, host, missing):
    runtime = replace(host["bindings"], **({"enabled_write_kinds": frozenset()} if missing == "gate" else {"writers": {}}))
    with bind_operator_runtime(runtime):
        async with Client(server) as client:
            review = await reviewed_request(client, host)
            denied = await request(client, host, "execute_bound", review, expect_error=True)
            assert denied["isError"] and not host["ledger"].exists()
            host["proof"] = signed(host["key"], host["claims"]("another-request"))
            result = await client.call_tool("tp_ironman_request", command("execute_bound", review))
            assert json.loads(result.content[0].text)["error_code"] == "OPERATOR_REQUEST_DENIED"
            assert not host["provider"].writes


async def test_mcp_recovers_orphan_without_reactivating_revoked_approval(prefect_runtime, host):
    from test_ironman_worker_recovery import orphan
    with bind_operator_runtime(host["bindings"]):
        async with Client(server) as client:
            review = await reviewed_request(client, host)
            host["provider"].lose_response = True
            result = await request(client, host, "execute_bound", review)
            assert result["results"][0]["state"] == "UNKNOWN_NEEDS_READBACK"
            store = DraftStore(host["store"])
            try:
                bound = store.inspect_execution_binding(review["request_id"], review["preview_sha256"],
                    review["approval_sha256"], approved_revision=REVISION, approval_scope=SCOPE,
                    requested_targets=command("execute_bound", review)["requested_targets"])
            finally:
                store.close()
            # Real child exit/abandoned kernel-lock slot is fault injection;
            # the uncertain write above traversed the actual adapter/engine.
            owner = orphan(host["ledger"], bound["manifest"])
            await request(client, host, "revoke_approval", review)
            host["provider"].unreadable = False
            recovery = {**review, "schema": "IRONMAN_RECOVERY_INPUT_V1", "worker_owner": owner}
            recovered = await request(client, host, "recover_worker", recovery)
            assert recovered["state"] == "WORKER_RECOVERED"
            assert recovered["provider_writes"] == 0
            reads = host["provider"].reads
            repeated = await request(client, host, "recover_worker", recovery)
            assert repeated["reused"] is True and host["provider"].reads == reads
            assert host["provider"].writes == [(501, 101)]
            denied = await request(client, host, "execute_bound", review, expect_error=True)
            assert denied["isError"]
            ledger = Ledger(host["ledger"])
            try:
                assert ledger.status(review["request_id"], "patch01") == "DONE_VERIFIED"
                assert ledger.db.execute("SELECT count(*) FROM worker_recoveries").fetchone() == (1,)
                assert ledger.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (0,)
            finally:
                ledger.close()
