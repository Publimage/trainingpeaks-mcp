"""Exact release regression: API-only retransmission, no worker/provider runs."""

import asyncio
from uuid import UUID

import pytest
from prefect.client.orchestration import get_client
from prefect.client.schemas.actions import WorkPoolCreate
from test_ironman_prefect_runtime import prefect_runtime  # noqa: F401 — shared API fixture

from scripts.ironman_jobs.ironman_prefect_dispatch import DispatchIdentity, PrefectProcessLauncher
from scripts.ironman_jobs.ironman_unified_changeset_engine import digest
from scripts.ironman_jobs.ironman_unified_prefect_flow import unified_changeset_flow


async def test_retransmission_reuses_one_flow_without_reprovisioning(prefect_runtime):  # noqa: F811
    pool = "ironman-prefect-staging-process"
    async with get_client() as api:
        await api.create_work_pool(WorkPoolCreate(name=pool, type="process"))
    deployment = await unified_changeset_flow.to_deployment(name="scoped-plan-preview-once", work_pool_name=pool)
    deployment_id = await deployment.apply()
    issued = []

    def provision(flow_id, command):
        issued.append(flow_id)

    command = {
        "mode": "prepare",
        "manifest": {"schema": "IRONMAN_OPERATION_INPUT_V1", "items": []},
        "requested_targets": [],
    }
    identity = DispatchIdentity("synthetic-issuer", "user-one", "stable-admitted-intent")

    def launcher(who=identity):
        return PrefectProcessLauncher(deployment_id, provision, resolve_identity=lambda _: who, timeout=0)

    # Two producers racing one logical request must have one provisioning owner.
    first, concurrent = await asyncio.gather(launcher()._dispatch(command), launcher()._dispatch(command))
    async with get_client() as api:
        original_state = (await api.read_flow_run(UUID(first["flow_run_id"]))).state_id
    second = await launcher()._dispatch(command)  # Producer restart / reconnect.
    assert first["flow_run_id"] == second["flow_run_id"]
    assert first["flow_run_id"] == concurrent["flow_run_id"]
    assert issued == [first["flow_run_id"]]
    async with get_client() as api:
        assert (await api.read_flow_run(UUID(first["flow_run_id"]))).state_id == original_state
    with pytest.raises(PermissionError, match="DISPATCH_INTENT_COMMAND_CONFLICT"):
        await launcher()._dispatch({**command, "manifest": {**command["manifest"], "request_key": "altered"}})
    other = await launcher(DispatchIdentity(identity.issuer, "user-two", identity.intent_id))._dispatch(command)
    assert other["flow_run_id"] != first["flow_run_id"]
    # A historical receipt must never be represented as a fresh provider check.
    from prefect.client.schemas.actions import ArtifactCreate
    from prefect.states import Completed

    async with get_client() as api:
        await api.create_artifact(
            ArtifactCreate(
                key="ironman-request-" + first["flow_run_id"],
                type="result",
                flow_run_id=UUID(first["flow_run_id"]),
                data={
                    "schema": "IRONMAN_OPERATOR_RECEIPT_V1",
                    "flow_run_id": first["flow_run_id"],
                    "command_sha256": digest(command),
                    "result": {"request_state": "WORK_COMPLETE"},
                },
            )
        )
        await api.set_flow_run_state(UUID(first["flow_run_id"]), Completed())
    replay = await launcher()._dispatch(command)
    assert replay["request_state"] == "DISPATCH_RESULT_REUSED"
    assert replay["historical_result"]["request_state"] == "WORK_COMPLETE"
    assert replay["new_execution"] is False
    assert issued == [first["flow_run_id"], other["flow_run_id"]]
    delivery_attempts = []

    def lost_delivery(*_):
        delivery_attempts.append(True)
        raise ConnectionError("SYNTHETIC_DELIVERY_ACK_LOST")

    failure_scope = DispatchIdentity(identity.issuer, identity.subject, "delivery-uncertain")
    failed_launcher = PrefectProcessLauncher(
        deployment_id, lost_delivery, resolve_identity=lambda _: failure_scope, timeout=0
    )
    failed = await failed_launcher._dispatch(command)
    failed_replay = await failed_launcher._dispatch(command)
    assert failed["flow_run_id"] == failed_replay["flow_run_id"]
    assert failed["provider_retry_allowed"] is False
    assert failed_replay["request_state"] == "DISPATCH_UNCERTAIN"
    assert len(delivery_attempts) == 1
    async with get_client() as api:
        held = await api.read_flow_run(UUID(failed["flow_run_id"]))
        assert held.state.is_pending() and held.state.name == "AwaitingTrustedInvocation"
        assert held.next_scheduled_start_time is None
        # This is the same API polled by ProcessWorker, without starting it.
        offered = await api.get_scheduled_flow_runs_for_work_pool(pool)
        assert held.id not in {item.flow_run.id for item in offered}


@pytest.mark.parametrize("identity", [None, "unverified-user", {"subject": "admin"}])
async def test_dispatch_requires_trusted_identity_before_api_access(identity):
    launcher = PrefectProcessLauncher(UUID(int=1), lambda *_: None, resolve_identity=lambda _: identity, timeout=0)
    with pytest.raises(PermissionError, match="TRUSTED_DISPATCH_IDENTITY_REQUIRED"):
        await launcher._dispatch({"mode": "prepare", "manifest": {}, "requested_targets": []})


@pytest.mark.parametrize("failed_read", ["state", "receipt"])
async def test_transport_uncertainty_preserves_flow_handle_without_resubmission(failed_read):
    from types import SimpleNamespace

    from prefect.states import Completed

    class Unavailable:
        async def read_flow_run(self, *_):
            if failed_read == "state":
                raise ConnectionError("SYNTHETIC_STATE_UNAVAILABLE")
            return SimpleNamespace(state=Completed())

        async def request(self, *_args, **_kwargs):
            raise ConnectionError("SYNTHETIC_RECEIPT_UNAVAILABLE")

    launcher = PrefectProcessLauncher(
        UUID(int=1), lambda *_: None, resolve_identity=lambda _: DispatchIdentity("issuer", "user", "intent"), timeout=0
    )
    result = await launcher._observe(Unavailable(), UUID(int=2), {}, reused=True)
    assert result["flow_run_id"] == str(UUID(int=2))
    assert result["provider_retry_allowed"] is False
    assert "historical_result" not in result


@pytest.mark.parametrize("failure_stage", ["allocation", "release"])
async def test_uncertain_allocation_or_release_never_repeats_issuer_or_cancels_running_work(monkeypatch, failure_stage):
    from types import SimpleNamespace

    issued, transitions = [], []
    command = {"mode": "prepare", "manifest": {}, "requested_targets": []}

    class API:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def read_deployment(self, *_):
            return SimpleNamespace(
                work_pool_name="ironman-prefect-staging-process",
                parameters={},
                entrypoint="scripts/ironman_jobs/ironman_unified_prefect_flow.py:unified_changeset_flow",
            )

        async def create_flow_run_from_deployment(self, *_args, **kwargs):
            if failure_stage == "allocation":
                raise ConnectionError("SYNTHETIC_CREATE_ACK_LOST")
            return SimpleNamespace(id=UUID(int=2), parameters=command, labels=kwargs["labels"], state=kwargs["state"])

        async def set_flow_run_state(self, _flow_id, state):
            transitions.append(state.type.value)
            raise ConnectionError("SYNTHETIC_RELEASE_ACK_LOST")

    monkeypatch.setattr("prefect.client.orchestration.get_client", lambda: API())
    launcher = PrefectProcessLauncher(
        UUID(int=1),
        lambda *_: issued.append(True),
        resolve_identity=lambda _: DispatchIdentity("issuer", "user", "intent"),
        timeout=0,
    )
    result = await launcher._dispatch(command)
    assert result["request_state"] == "DISPATCH_UNCERTAIN"
    assert result["provider_retry_allowed"] is False
    if failure_stage == "allocation":
        assert result["flow_run_id"] is None and result["dispatch_key"]
        assert not issued and not transitions
    else:
        assert result["flow_run_id"] == str(UUID(int=2))
        assert issued == [True] and transitions == ["SCHEDULED"]


async def test_creator_does_not_issue_or_reset_an_already_advanced_run(monkeypatch):
    from types import SimpleNamespace

    from prefect.states import Running

    calls = []
    command = {"mode": "prepare", "manifest": {}, "requested_targets": []}

    class API:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def read_deployment(self, *_):
            return SimpleNamespace(
                work_pool_name="ironman-prefect-staging-process",
                parameters={},
                entrypoint="scripts/ironman_jobs/ironman_unified_prefect_flow.py:unified_changeset_flow",
            )

        async def create_flow_run_from_deployment(self, *_args, **kwargs):
            return SimpleNamespace(id=UUID(int=2), parameters=command, labels=kwargs["labels"], state=Running())

        async def set_flow_run_state(self, *_):
            calls.append("state-change")

    monkeypatch.setattr("prefect.client.orchestration.get_client", lambda: API())
    launcher = PrefectProcessLauncher(
        UUID(int=1),
        lambda *_: calls.append("issue"),
        resolve_identity=lambda _: DispatchIdentity("issuer", "user", "intent"),
        timeout=0,
    )
    with pytest.raises(PermissionError, match="DISPATCH_INITIAL_HOLD_REQUIRED"):
        await launcher._dispatch(command)
    assert calls == []
