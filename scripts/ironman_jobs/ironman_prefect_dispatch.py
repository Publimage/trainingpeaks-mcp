"""Host-only launcher into the existing Prefect process work pool.

Only the three domain fields cross the API. Provisioning signed invocation
evidence is a trusted issuer port, never a serialized callback or client token.
"""

import asyncio
import time
from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID, uuid4

from scripts.ironman_jobs.ironman_authorization import require
from scripts.ironman_jobs.ironman_unified_changeset_engine import digest


@dataclass(frozen=True)
class DispatchIdentity:
    """Verified ingress identity and stable logical intent, supplied by host code.

    intent_id survives transport retries, reconnects and bearer-token rotation.
    A separately admitted new operation gets a new intent; clients cannot supply
    this object through domain parameters. It is not a bearer token or flow ID.
    """

    issuer: str
    subject: str
    intent_id: str

    def __post_init__(self):
        require(
            all(type(x) is str and 0 < len(x) <= 256 for x in (self.issuer, self.subject, self.intent_id)),
            "DISPATCH_IDENTITY_INVALID",
        )


class PrefectProcessLauncher:
    def __init__(self, deployment_id, provision_invocation, *, resolve_identity, timeout=90):
        self.deployment_id = UUID(str(deployment_id))
        require(callable(provision_invocation), "TRUSTED_ISSUER_PORT_REQUIRED")
        require(callable(resolve_identity), "TRUSTED_DISPATCH_IDENTITY_REQUIRED")
        self.provision_invocation, self.timeout = provision_invocation, timeout
        self.resolve_identity = resolve_identity

    def __call__(self, manifest, ledger_path, *, mode, read_transport, requested_targets):
        # Host-only paths/transport are deliberately NOT forwarded to the worker.
        command = {"mode": mode, "manifest": manifest, "requested_targets": requested_targets}
        return asyncio.run(self._dispatch(command))

    async def _dispatch(self, command):
        from prefect.client.orchestration import get_client
        from prefect.states import Pending, Scheduled

        command = deepcopy(command)
        identity = self.resolve_identity(deepcopy(command))
        require(isinstance(identity, DispatchIdentity), "TRUSTED_DISPATCH_IDENTITY_REQUIRED")
        key = "ironman-dispatch-" + digest(
            [str(self.deployment_id), identity.issuer, identity.subject, identity.intent_id]
        )
        # A nonce identifies this creation attempt only. The persisted label
        # belongs to the atomic create winner; it is never worker authority.
        owner = str(uuid4())
        async with get_client() as client:
            deployment = await client.read_deployment(self.deployment_id)
            entrypoint = "scripts/ironman_jobs/ironman_unified_prefect_flow.py:unified_changeset_flow"
            require(
                deployment.work_pool_name == "ironman-prefect-staging-process" and deployment.entrypoint == entrypoint,
                "PREFECT_DEPLOYMENT_NOT_PINNED",
            )
            require(
                set(deployment.parameters) <= {"mode", "manifest", "requested_targets"},
                "PREFECT_PRIVILEGED_DEFAULTS_FORBIDDEN",
            )
            try:
                run = await client.create_flow_run_from_deployment(
                    self.deployment_id,
                    parameters=command,
                    idempotency_key=key,
                    labels={"ironman.dispatch-owner": owner},
                    state=Pending(name="AwaitingTrustedInvocation"),
                )
            except Exception:
                return {
                    "isError": True,
                    "error_code": "DISPATCH_ALLOCATION_UNCONFIRMED",
                    "request_state": "DISPATCH_UNCERTAIN",
                    "dispatch_key": key,
                    "flow_run_id": None,
                    "provider_retry_allowed": False,
                }
            require(digest(run.parameters) == digest(command), "DISPATCH_INTENT_COMMAND_CONFLICT")
            reused = run.labels.get("ironman.dispatch-owner") != owner
            if not reused:
                # A native non-scheduled state cannot be polled by the worker.
                # No clock-based hold: partial issuer delivery must never become
                # executable later merely because a scheduled time has elapsed.
                require(
                    run.state is not None and run.state.is_pending() and run.state.name == "AwaitingTrustedInvocation",
                    "DISPATCH_INITIAL_HOLD_REQUIRED",
                )
                try:
                    self.provision_invocation(str(run.id), deepcopy(command))
                except Exception:
                    # Delivery may have committed. Leave the run held and never
                    # issue, release or cancel it on a transport retransmission.
                    return {
                        "isError": True,
                        "error_code": "INVOCATION_DELIVERY_UNCONFIRMED",
                        "request_state": "DISPATCH_UNCERTAIN",
                        "flow_run_id": str(run.id),
                        "provider_retry_allowed": False,
                    }
                try:
                    await client.set_flow_run_state(run.id, Scheduled())
                except Exception:
                    # Release may have committed. Do not cancel or issue again.
                    return self._uncertain(run.id)
            return await self._observe(client, run.id, command, reused=reused)

    async def _observe(self, client, flow_id, command, *, reused):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                observed = await client.read_flow_run(flow_id)
            except Exception:
                return self._uncertain(flow_id)
            if observed.state and observed.state.is_final():
                if not observed.state.is_completed():
                    return {
                        "isError": True,
                        "error_code": "PREFECT_WORKER_FLOW_DENIED_OR_FAILED",
                        "flow_run_id": str(flow_id),
                        "provider_retry_allowed": False,
                    }
                try:
                    receipt = await self._receipt(client, flow_id, command)
                except Exception:
                    return {
                        "isError": True,
                        "error_code": "WORKER_RECEIPT_UNVERIFIED",
                        "flow_run_id": str(flow_id),
                        "provider_retry_allowed": False,
                    }
                if reused:
                    return {
                        "request_state": "DISPATCH_RESULT_REUSED",
                        "flow_run_id": str(flow_id),
                        "historical_result": receipt["result"],
                        "new_execution": False,
                        "provider_retry_allowed": False,
                    }
                return receipt["result"]
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.25)
        return self._uncertain(flow_id)

    @staticmethod
    def _uncertain(flow_id):
        return {"request_state": "DISPATCH_UNCERTAIN", "flow_run_id": str(flow_id), "provider_retry_allowed": False}

    async def _receipt(self, client, flow_id, command):
        # The bounded API body omits SDK 3.8.8's invalid null filter defaults.
        response = await client.request(
            "POST",
            "/artifacts/filter",
            json={
                "artifacts": {
                    "flow_run_id": {"any_": [str(flow_id)]},
                    "key": {"any_": ["ironman-request-" + str(flow_id)]},
                },
                "limit": 2,
                "offset": 0,
                "sort": "CREATED_DESC",
            },
        )
        receipts = [a["data"] for a in response.json()]
        require(len(receipts) == 1, "WORKER_RECEIPT_MISSING_OR_DUPLICATE")
        receipt = receipts[0]
        require(
            type(receipt) is dict
            and receipt.get("schema") == "IRONMAN_OPERATOR_RECEIPT_V1"
            and receipt.get("flow_run_id") == str(flow_id)
            and receipt.get("command_sha256") == digest(command)
            and type(receipt.get("result")) is dict,
            "WORKER_RECEIPT_BINDING_MISMATCH",
        )
        return receipt
