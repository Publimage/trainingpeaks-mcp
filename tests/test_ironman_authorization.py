"""Real signature verification and persistent grants; synthetic issuer keys only."""
import base64
import copy
import json
import os
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

from scripts.ironman_jobs.ironman_authorization import (
    ACTIONS, HostReviewAuthority, SignedIdentityVerifier, read_host_file,
)
from scripts.ironman_jobs.ironman_dynamic_request_store import canonical
from scripts.ironman_jobs.ironman_unified_changeset_engine import ChangeStop
import test_ironman_preview_approval as preview_fixtures

context, real_flow = preview_fixtures.context, preview_fixtures.real_flow
control, call_flow, SCOPE = preview_fixtures.control, preview_fixtures.call_flow, preview_fixtures.SCOPE


def compact(value):
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def signed(key, claims, header=None):
    header = header or {"alg": "EdDSA", "kid": "test-key", "typ": "JWT"}
    content = compact(header) + "." + compact(claims)
    signature = (key.sign(content.encode(), padding.PKCS1v15(), hashes.SHA256())
                 if isinstance(key, rsa.RSAPrivateKey) else key.sign(content.encode()))
    return content + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


@pytest.fixture
def authority(context, tmp_path, monkeypatch):
    key = ed25519.Ed25519PrivateKey.generate()
    now = [int(time.time())]
    config = {"issuer": "https://synthetic-issuer.invalid", "audience": "ironman-operator-test",
              "required_scope": "ironman:operator", "administrators": ["test-admin"],
              "keys": {"test-key": {"algorithm": "EdDSA", "public_key_pem": key.public_key().public_bytes(
                  serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()}}}
    claims = {"iss": config["issuer"], "aud": config["audience"], "sub": "test-user", "jti": "user-token",
              "iat": now[0] - 1, "nbf": now[0] - 1, "exp": now[0] + 600, "scope": "ironman:operator",
              "run_id": "synthetic-prefect-run"}
    reader = [signed(key, {**claims, "sub": "test-admin", "jti": "admin-token"})]
    verifier = SignedIdentityVerifier(config, clock=lambda: now[0])
    service = HostReviewAuthority(context["path"], verifier, lambda: reader[0], clock=lambda: now[0],
                                  invocation_id_provider=lambda: "synthetic-prefect-run")
    principal = verifier.verify(signed(key, claims))
    grant_id = service.grant(principal, context["draft"]["request_id"], context["preview"],
                             approval_scope=SCOPE, actions=sorted(ACTIONS), expires_at=now[0] + 300)
    config_path, token_path = tmp_path / "trust.json", tmp_path / "identity.jwt"
    config_path.write_text(json.dumps(config))
    os.chmod(config_path, 0o600)

    def select(subject="test-user", **changes):
        token = signed(key, {**claims, "sub": subject, "jti": "admin-token" if subject == "test-admin" else "user-token",
                             **changes})
        reader[0] = token
        token_path.write_text(token)
        os.chmod(token_path, 0o600)
        return token

    select()
    monkeypatch.setenv("IRONMAN_REVIEW_TRUST_CONFIG", str(config_path))
    monkeypatch.setenv("IRONMAN_REVIEW_ASSERTION_FILE", str(token_path))
    monkeypatch.setenv("IRONMAN_OPERATION_DRAFT_STORE", str(context["path"]))
    command = {"action": "approve_preview", "review": control(context), "manifest": context["manifest"],
               "requested_targets": context["review"]["requested_targets"]}
    return dict(service=service, verifier=verifier, claims=claims, config=config, key=key, now=now,
                reader=reader, select=select, grant=grant_id, principal=principal, command=command,
                config_path=config_path, token_path=token_path)


@pytest.mark.parametrize("change", [
    {"iss": "https://other.invalid"}, {"aud": "another-service"}, {"sub": ""}, {"jti": ""},
    {"scope": "unrelated"}, {"exp": 1}, {"exp": True}, {"nbf": 9999999999}, {"iat": 9999999999},
])
def test_signed_but_invalid_identity_claims_are_refused(authority, change):
    token = signed(authority["key"], {**authority["claims"], **change})
    with pytest.raises(PermissionError):
        authority["verifier"].verify(token)


@pytest.mark.parametrize("header", [
    {"alg": "none", "kid": "test-key"}, {"alg": "HS256", "kid": "test-key"},
    {"alg": "RS256", "kid": "test-key"}, {"alg": "EdDSA", "kid": "unknown"},
    {"alg": "EdDSA", "kid": "test-key", "jku": "https://untrusted.invalid/keys"},
])
def test_token_cannot_choose_another_algorithm_or_key_source(authority, header):
    with pytest.raises(PermissionError):
        authority["verifier"].verify(signed(authority["key"], authority["claims"], header))


def test_invalid_signature_is_refused(authority):
    impostor = ed25519.Ed25519PrivateKey.generate()
    with pytest.raises(PermissionError, match="SIGNATURE_INVALID"):
        authority["verifier"].verify(signed(impostor, authority["claims"]))


def test_rsa_pinned_key_and_audience_list_are_supported(authority):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    config = copy.deepcopy(authority["config"])
    config["keys"]["test-key"] = {"algorithm": "RS256", "public_key_pem": key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()}
    verifier = SignedIdentityVerifier(config, clock=lambda: authority["now"][0])
    claims = {**authority["claims"], "aud": ["other", config["audience"]]}
    assert verifier.verify(signed(key, claims, {"alg": "RS256", "kid": "test-key"})).subject == "test-user"


def test_regular_caller_cannot_grant_itself_more_permissions(context, authority):
    with pytest.raises(PermissionError, match="ADMIN_REQUIRED"):
        authority["service"].grant(authority["principal"], context["draft"]["request_id"], context["preview"],
                                     approval_scope=SCOPE, actions=["execute_change"], expires_at=authority["now"][0] + 100)


@pytest.mark.parametrize("mutation", ["action", "scope", "revision", "target", "item", "subject"])
def test_grant_is_bound_to_exact_identity_request_and_operation(context, authority, mutation):
    command = copy.deepcopy(authority["command"])
    if mutation == "action":
        command["action"] = "unsupported-admin-action"
    elif mutation == "scope":
        command["review"]["approval_scope"] = "approved:another-scope"
    elif mutation == "revision":
        command["review"]["reviewed_revision"] = "b" * 40
    elif mutation == "target":
        command["manifest"]["changes"][0]["target"]["container_id"] = 999
    elif mutation == "item":
        command["item"] = {"id": "another-item"}
    else:
        authority["select"]("another-user")
    assert authority["service"].authorize(command) is False


def test_grant_expiration_is_checked_on_each_use(authority):
    assert authority["service"].authorize(authority["command"]) is True
    authority["now"][0] += 301
    assert authority["service"].authorize(authority["command"]) is False


@pytest.mark.parametrize("kind", ["grant", "token", "principal", "grantor"])
def test_persistent_revocation_is_checked_on_each_use(authority, kind):
    assert authority["service"].authorize(authority["command"]) is True
    authority["select"]("test-admin")
    identity = authority["grant"] if kind == "grant" else canonical([
        authority["config"]["issuer"], "user-token" if kind == "token" else
        "test-admin" if kind == "grantor" else "test-user"])
    authority["service"].revoke("principal" if kind == "grantor" else kind, identity)
    authority["select"]()
    assert authority["service"].authorize(authority["command"]) is False


def test_authority_audit_contains_actor_and_decision_but_no_assertion(context, authority):
    raw_token = authority["reader"][0]
    assert authority["service"].authorize(authority["command"])
    authority["reader"][0] = "invalid-assertion"
    assert not authority["service"].authorize(authority["command"])
    rows = context["store"].db.execute("SELECT subject,action,allowed,code FROM authority_audit ORDER BY sequence").fetchall()
    assert rows[-2] == ("test-user", "approve_preview", 1, "AUTHORIZED")
    assert rows[-1] == (None, "approve_preview", 0, "IDENTITY_UNVERIFIED")
    assert raw_token not in json.dumps(context["store"].db.execute("SELECT * FROM authority_audit").fetchall())


def test_flow_uses_real_crypto_authority_and_rechecks_revoked_grant(context, authority, real_flow, tmp_path):
    # No monkeypatch of get_review_authorizer or authorize: factory reads real
    # private host files and verifies the synthetic issuer's actual signature.
    approval = call_flow(real_flow, context, tmp_path, "approve_preview")
    bound = call_flow(real_flow, context, tmp_path, "bind_execution", approval)
    assert bound["state"] == "EXECUTION_BOUND"
    authority["select"]("test-admin")
    authority["service"].revoke("grant", authority["grant"])
    authority["select"]()
    with pytest.raises(ChangeStop, match="REVIEW_AUTHORIZATION_DENIED"):
        call_flow(real_flow, context, tmp_path, "bind_execution", approval)
    assert not (tmp_path / "must-not-open.sqlite3").exists()


@pytest.mark.parametrize("unsafe", ["permissions", "symlink"])
def test_host_assertion_file_is_private_and_not_a_symlink(authority, tmp_path, unsafe):
    path = authority["token_path"]
    if unsafe == "permissions":
        os.chmod(path, 0o644)
    else:
        link = tmp_path / "assertion-link"
        link.symlink_to(path)
        path = link
    with pytest.raises(PermissionError):
        read_host_file(path, 32768)


def test_real_authority_recovers_revoked_binding_via_existing_flow(context, authority, real_flow, tmp_path, monkeypatch):
    from scripts.ironman_jobs.ironman_unified_changeset_engine import Ledger, SecurityDenied, run_changeset
    from scripts.ironman_jobs.ironman_operation_contracts import BoundExecutionAuthorization
    from test_ironman_worker_recovery import orphan, Reader
    approval = call_flow(real_flow, context, tmp_path, "approve_preview")
    bound = call_flow(real_flow, context, tmp_path, "bind_execution", approval)
    call_flow(real_flow, context, tmp_path, "revoke_approval", approval)
    path = tmp_path / "recovery-ledger.sqlite3"
    owner = orphan(path, bound["manifest"])
    monkeypatch.setenv("IRONMAN_OPERATION_EXECUTION_LEDGER", str(path))
    reader = Reader({"title": "after"})
    monkeypatch.setattr(real_flow, "create_read_registry", lambda _: {"plan.workout.patch": reader})
    request = {**control(context, approval), "schema": "IRONMAN_RECOVERY_INPUT_V1", "worker_owner": owner}
    recovered = real_flow.unified_changeset_flow.fn(request, str(path), mode="recover_worker",
                                                     requested_targets=context["review"]["requested_targets"])
    assert recovered["provider_writes"] == reader.writes == 0
    assert recovered["state"] == "WORKER_RECOVERED"
    assert recovered["reconciliation_required"] is False
    ledger = Ledger(path)
    try:
        assert ledger.status(context["draft"]["request_id"], "patch01") == "DONE_VERIFIED"
        assert ledger.db.execute("SELECT count(*) FROM execution_workers").fetchone() == (0,)
        # Successful recovery does not reactivate the withdrawn approval.
        guard = BoundExecutionAuthorization(context["path"], context["draft"]["request_id"],
                                            context["preview"], approval["approval_sha256"], **context["review"])
        with pytest.raises(SecurityDenied):
            run_changeset(bound["manifest"], {"plan.workout.patch": reader}, ledger, execute=True,
                          reviewed_revision=context["review"]["approved_revision"], approval_scope=SCOPE,
                          authorize_execution=guard)
    finally:
        ledger.close()


def test_recovery_requires_its_own_grant_before_any_provider_read(context, authority, real_flow, tmp_path, monkeypatch):
    from test_ironman_worker_recovery import orphan
    approval = call_flow(real_flow, context, tmp_path, "approve_preview")
    bound = call_flow(real_flow, context, tmp_path, "bind_execution", approval)
    authority["select"]("test-admin")
    authority["service"].revoke("grant", authority["grant"])
    authority["service"].grant(authority["principal"], context["draft"]["request_id"], context["preview"],
                                 approval_scope=SCOPE, actions=["approve_preview", "bind_execution"],
                                 expires_at=authority["now"][0] + 200)
    authority["select"]()
    path = tmp_path / "restricted-ledger.sqlite3"
    owner = orphan(path, bound["manifest"])
    monkeypatch.setenv("IRONMAN_OPERATION_EXECUTION_LEDGER", str(path))
    request = {**control(context, approval), "schema": "IRONMAN_RECOVERY_INPUT_V1", "worker_owner": owner}
    with pytest.raises(PermissionError):
        real_flow.unified_changeset_flow.fn(request, str(path), mode="recover_worker",
                                             requested_targets=context["review"]["requested_targets"])


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_run_control_rolls_back_completed_inner_savepoint(context, authority, monkeypatch, error_type):
    original = context["store"].record_approval

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise error_type("simulated transaction interruption")

    monkeypatch.setattr(context["store"], "record_approval", interrupted)
    with pytest.raises(error_type):
        authority["service"].run_control(authority["command"], context["store"])
    assert context["store"].db.execute("SELECT count(*) FROM preview_approvals").fetchone() == (0,)
    assert not context["store"].db.in_transaction


def test_revocation_and_control_action_have_one_serial_order(context, authority, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from scripts.ironman_jobs.ironman_dynamic_request_store import DraftStore
    entered, release = Event(), Event()
    # Pause after successful policy evaluation while the real authority holds
    # the same SQLite writer transaction as the pending control mutation.
    def perform():
        store = DraftStore(context["path"])
        try:
            # Use this thread's store connection for the persistence operation.
            def thread_record(*args, **kwargs):
                entered.set()
                assert release.wait(timeout=5)
                return DraftStore.record_approval(store, *args, **kwargs)
            monkeypatch.setattr(store, "record_approval", thread_record)
            return authority["service"].run_control(authority["command"], store)
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(perform)
        try:
            assert entered.wait(timeout=5)
            competing = context["store"].db
            competing.execute("PRAGMA busy_timeout=0")
            import sqlite3
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing.execute("BEGIN IMMEDIATE")
        finally:
            release.set()
        assert future.result(timeout=10)["state"] == "APPROVAL_RECORDED"
    authority["select"]("test-admin")
    authority["service"].revoke("grant", authority["grant"])
    authority["select"]()
    assert not authority["service"].authorize(authority["command"])


def test_signed_identity_cannot_be_reused_by_another_prefect_invocation(authority):
    authority["service"].invocation_id_provider = lambda: "another-prefect-run"
    assert authority["service"].authorize(authority["command"]) is False


def test_invocation_binding_is_mandatory_in_assertion(authority):
    claims = dict(authority["claims"])
    del claims["run_id"]
    with pytest.raises(PermissionError, match="PRINCIPAL_REQUIRED"):
        authority["verifier"].verify(signed(authority["key"], claims))


def test_flow_payload_cannot_supply_principal_or_authority(context, authority, real_flow, tmp_path):
    payload = {**control(context), "principal": "test-admin"}
    with pytest.raises(ChangeStop, match="REVIEW_INPUT_SHAPE"):
        real_flow.unified_changeset_flow.fn(payload, str(tmp_path / "never-open.sqlite3"), mode="approve_preview",
                                             requested_targets=context["review"]["requested_targets"])
    assert context["store"].db.execute("SELECT count(*) FROM preview_approvals").fetchone() == (0,)


def test_grant_retry_is_idempotent_but_cannot_resurrect_revocation(context, authority):
    authority["select"]("test-admin")
    options = dict(approval_scope=SCOPE, actions=sorted(ACTIONS), expires_at=authority["now"][0] + 300)
    assert authority["service"].grant(authority["principal"], context["draft"]["request_id"],
                                        context["preview"], **options) == authority["grant"]
    authority["service"].revoke("grant", authority["grant"])
    with pytest.raises(PermissionError, match="GRANT_REVOKED"):
        authority["service"].grant(authority["principal"], context["draft"]["request_id"],
                                     context["preview"], **options)
