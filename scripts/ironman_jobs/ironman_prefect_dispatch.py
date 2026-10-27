"""Host-only launcher into the existing Prefect process work pool.

Only the three domain fields cross the API. Provisioning signed invocation
evidence is a trusted issuer port, never a serialized callback or client token.
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from scripts.ironman_jobs.ironman_authorization import require
from scripts.ironman_jobs.ironman_unified_changeset_engine import digest


class PrefectProcessLauncher:
    def __init__(self, deployment_id, provision_invocation, *, timeout=90):
        self.deployment_id = UUID(str(deployment_id))
        require(callable(provision_invocation), "TRUSTED_ISSUER_PORT_REQUIRED")
        self.provision_invocation, self.timeout = provision_invocation, timeout

    def __call__(self, manifest, ledger_path, *, mode, read_transport, requested_targets):
        # Host-only paths/transport are deliberately NOT forwarded to the worker.
        command = {"mode": mode, "manifest": manifest, "requested_targets": requested_targets}
        return asyncio.run(self._dispatch(command))

    async def _dispatch(self, command):
        from prefect.client.orchestration import get_client
        from prefect.states import Cancelled, Scheduled
        async with get_client() as client:
            deployment = await client.read_deployment(self.deployment_id)
            entrypoint = ("scripts/ironman_jobs/ironman_unified_prefect_flow.py:"
                          "unified_changeset_flow")
            require(deployment.work_pool_name == "ironman-prefect-staging-process" and
                    deployment.entrypoint == entrypoint,
                    "PREFECT_DEPLOYMENT_NOT_PINNED")
            require(set(deployment.parameters) <= {"mode", "manifest", "requested_targets"},
                    "PREFECT_PRIVILEGED_DEFAULTS_FORBIDDEN")
            run = await client.create_flow_run_from_deployment(self.deployment_id, parameters=command,
                idempotency_key="ironman-dispatch-" + str(uuid4()),
                state=Scheduled(scheduled_time=datetime.now(timezone.utc) + timedelta(days=1)))
            try:
                # Future scheduling keeps the worker from racing the host-only
                # issuer handoff. Missing evidence still denies inside the worker.
                self.provision_invocation(str(run.id), command)
            except Exception:
                await client.set_flow_run_state(run.id, Cancelled(message="Invocation provisioning failed"))
                raise
            await client.set_flow_run_state(run.id, Scheduled())
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                observed = await client.read_flow_run(run.id)
                if observed.state and observed.state.is_final():
                    if not observed.state.is_completed():
                        return {"isError": True, "error_code": "PREFECT_WORKER_FLOW_DENIED_OR_FAILED",
                                "flow_run_id": str(run.id), "provider_retry_allowed": False}
                    # Explicit API body omits unspecified filters. SDK 3.8.8's
                    # read_artifacts serializes them as null, rejected by its
                    # server schema. This is one bounded exact-key lookup using
                    # the same authenticated client, not a retry/fallback.
                    response = await client.request("POST", "/artifacts/filter", json={
                        "artifacts": {"flow_run_id": {"any_": [str(run.id)]},
                                      "key": {"any_": ["ironman-request-" + str(run.id)]}},
                        "limit": 2, "offset": 0, "sort": "CREATED_DESC"})
                    receipts = [a["data"] for a in response.json()]
                    require(len(receipts) == 1, "WORKER_RECEIPT_MISSING_OR_DUPLICATE")
                    receipt = receipts[0]
                    require(type(receipt) is dict and receipt.get("schema") == "IRONMAN_OPERATOR_RECEIPT_V1" and
                            receipt.get("flow_run_id") == str(run.id) and
                            receipt.get("command_sha256") == digest(command) and
                            type(receipt.get("result")) is dict, "WORKER_RECEIPT_BINDING_MISMATCH")
                    return receipt["result"]
                await asyncio.sleep(0.25)
            # Never resubmit on uncertain completion. The flow ID is the handle
            # for read-only reconciliation on the existing Prefect API.
            return {"request_state": "DISPATCH_UNCERTAIN", "flow_run_id": str(run.id),
                    "provider_retry_allowed": False}
