"""One native API hold recovery; real signatures/revocations, no worker/provider."""

import asyncio
import time
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import WorkPoolCreate
from test_ironman_authorization import signed
from test_ironman_prefect_runtime import prefect_runtime  # noqa: F401

from scripts.ironman_jobs.ironman_authorization import (
    HostReviewAuthority,
    SignedIdentityVerifier,
    assertion_path_for_invocation,
    delivered_invocation_reconciler,
)
from scripts.ironman_jobs.ironman_file_lock import exclusive_file_lock
from scripts.ironman_jobs.ironman_prefect_dispatch import DispatchIdentity, PrefectProcessLauncher
from scripts.ironman_jobs.ironman_unified_changeset_engine import digest
from scripts.ironman_jobs.ironman_unified_prefect_flow import unified_changeset_flow


@pytest.mark.usefixtures("prefect_runtime")
async def test_valid_delivered_assertion_resumes_same_held_flow_once_under_shared_fence(tmp_path):
    key = ed25519.Ed25519PrivateKey.generate()
    cfg = {
        "issuer": "https://synthetic.invalid",
        "audience": "worker",
        "required_scope": "ironman:operator",
        "administrators": ["admin"],
        "keys": {
            "test-key": {
                "algorithm": "EdDSA",
                "public_key_pem": key.public_key()
                .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
                .decode(),
            }
        },
    }
    verifier = SignedIdentityVerifier(cfg)
    store, directory, lock = tmp_path / "draft.sqlite3", tmp_path / "assertions", tmp_path / "dispatch.lock"
    directory.mkdir(mode=0o700)
    command = {"mode": "prepare", "manifest": {}, "requested_targets": []}
    identity = DispatchIdentity(cfg["issuer"], "alice", "same-admitted-intent")
    delivered, origin = [], []

    def token(run_id, subject="alice", **changes):
        now = int(time.time())
        return signed(
            key,
            {
                "iss": cfg["issuer"],
                "aud": cfg["audience"],
                "scope": cfg["required_scope"],
                "sub": subject,
                "jti": subject,
                "run_id": run_id,
                "iat": now - 1,
                "nbf": now - 1,
                "exp": now + 600,
                "command_sha256": digest(command),
                **changes,
            },
        )

    def admin(run_id):
        return HostReviewAuthority(
            store, verifier, lambda: token(run_id, "admin"), invocation_id_provider=lambda: run_id
        )

    def provision(run_id, payload):
        delivered.append(run_id)
        origin.append(run_id)
        admin(run_id).refresh_revocations(1)
        path = assertion_path_for_invocation(directory, run_id)
        path.write_text(token(run_id))
        path.chmod(0o600)
        raise ConnectionError("SYNTHETIC_DELIVERY_ACK_LOST")

    reconcile = delivered_invocation_reconciler(store, verifier, directory, revocation_max_age_seconds=300)
    async with get_client() as api:
        await api.create_work_pool(WorkPoolCreate(name="ironman-prefect-staging-process", type="process"))
    deployment = await unified_changeset_flow.to_deployment(
        name="scoped-plan-preview-once", work_pool_name="ironman-prefect-staging-process"
    )
    deployment_id = await deployment.apply()

    def launcher():
        return PrefectProcessLauncher(
            deployment_id,
            provision,
            resolve_identity=lambda _: identity,
            reconcile_invocation=reconcile,
            coordination_path=lock,
            timeout=0,
        )

    first = await launcher()._dispatch(command)
    run_id = first["flow_run_id"]
    path = assertion_path_for_invocation(directory, run_id)
    # The shared producer fence is respected, with no allocation or issuer retry.
    with exclusive_file_lock(lock):
        busy = await launcher()._dispatch(command)
        assert busy["error_code"] == "DISPATCH_COORDINATOR_BUSY"
    for bad in ("missing", "subject", "command", "expired", "stale", "revoked"):
        path.write_text(
            token(run_id, "bob")
            if bad == "subject"
            else token(run_id, command_sha256="0" * 64)
            if bad == "command"
            else token(run_id, exp=int(time.time()) - 1)
            if bad == "expired"
            else token(run_id)
        )
        if bad == "missing":
            path.unlink()
        if bad == "stale":
            import sqlite3

            with sqlite3.connect(store) as db:
                db.execute("UPDATE authority_revocation_checkpoint SET observed_at=0")
        if bad == "revoked":
            from scripts.ironman_jobs.ironman_dynamic_request_store import canonical

            path.write_text(token(run_id, jti="withdrawn"))
            admin(run_id).revoke("token", canonical([cfg["issuer"], "withdrawn"]))
            admin(run_id).refresh_revocations(2)
        result = await launcher()._dispatch(command)
        assert result["error_code"] == "DISPATCH_RECONCILIATION_UNCONFIRMED"
        async with get_client() as api:
            assert (await api.read_flow_run(UUID(run_id))).state.is_pending()
    admin(run_id).refresh_revocations(2)
    path.write_text(token(run_id))
    path.chmod(0o600)
    results = await asyncio.gather(launcher()._dispatch(command), launcher()._dispatch(command))
    assert sum(bool(r.get("dispatch_resumed")) for r in results) == 1
    assert delivered == [run_id]
    async with get_client() as api:
        released = await api.read_flow_run(UUID(run_id))
        assert released.state.is_scheduled()
        state_id = released.state_id
    await launcher()._dispatch(command)
    async with get_client() as api:
        assert (await api.read_flow_run(UUID(run_id))).state_id == state_id
    assert delivered == [run_id]
