"""Reconstitute the ONE universal flow from protected worker-local inputs.

No module name, callback, credential or runtime path comes from flow parameters.
Production writers are absent. A trusted process bootstrap may install reviewed
adapters in code; each still needs a separate host capability gate.
"""
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from scripts.ironman_jobs.ironman_authorization import (
    _json,
    authority_from_host,
    current_invocation_id,
    read_host_file,
    require,
)
from scripts.ironman_jobs.ironman_unified_changeset_engine import digest
from tp_mcp.operator_runtime import MODES, bind_operator_runtime

_adapter_factory = None


def install_worker_adapters(factory):
    """Trusted process startup only; there is no request-selected plugin loader."""
    global _adapter_factory
    require(callable(factory) and _adapter_factory is None, "WORKER_ADAPTER_BOOTSTRAP_INVALID")
    _adapter_factory = factory


def validate_worker_command(command):
    # The existing read-only deployment also supports its original preview
    # operation. It still needs the same signed request and freshness gate.
    require(type(command) is dict and set(command) == {"mode", "manifest", "requested_targets"} and
            type(command["mode"]) is str and command["mode"] in (*MODES, "preview") and
            type(command["manifest"]) is dict and type(command["requested_targets"]) is list,
            "WORKER_COMMAND_SHAPE")


@contextmanager
def worker_request(command, *, flow_source):
    from prefect.context import get_run_context

    from scripts.ironman_jobs.ironman_unified_prefect_flow import compose_operator_runtime

    config_path = os.environ.get("IRONMAN_OPERATOR_WORKER_CONFIG")
    require(bool(config_path), "WORKER_PROTECTED_CONFIG_REQUIRED")
    cfg = _json(read_host_file(Path(config_path), 65536))
    fields = {"deployment_id", "flow_sha256", "draft_store", "ledger_path", "trust_config",
              "assertion_directory", "read_transport", "revocation_max_age_seconds", "enabled_write_kinds"}
    require(type(cfg) is dict and set(cfg) == fields, "WORKER_CONFIG_SHAPE")
    run = get_run_context().flow_run
    require(set(run.parameters) <= {"mode", "manifest", "requested_targets", "ledger_path", "read_transport"} and
            run.parameters.get("ledger_path") is None and run.parameters.get("read_transport") is None,
            "WORKER_PRIVILEGED_PARAMETERS_FORBIDDEN")
    require(str(run.deployment_id) == str(UUID(cfg["deployment_id"])), "WORKER_DEPLOYMENT_MISMATCH")
    source = Path(flow_source)
    require(hashlib.sha256(source.read_bytes()).hexdigest() == cfg["flow_sha256"], "WORKER_CODE_MISMATCH")
    validate_worker_command(command)
    require(cfg["read_transport"] in {"local", "private_bridge"}, "WORKER_TRANSPORT_INVALID")
    require(type(cfg["revocation_max_age_seconds"]) is int and
            1 <= cfg["revocation_max_age_seconds"] <= 300, "WORKER_REVOCATION_POLICY_REQUIRED")
    require(type(cfg["enabled_write_kinds"]) is list and
            all(type(k) is str for k in cfg["enabled_write_kinds"]), "WORKER_CAPABILITIES_INVALID")
    mapping = {"IRONMAN_OPERATION_DRAFT_STORE": "draft_store", "IRONMAN_OPERATION_EXECUTION_LEDGER": "ledger_path",
               "IRONMAN_REVIEW_TRUST_CONFIG": "trust_config",
               "IRONMAN_REVIEW_ASSERTION_DIRECTORY": "assertion_directory"}
    # No fallback to caller values or another store/issuer.
    for variable, key in mapping.items():
        require(type(cfg[key]) is str and Path(cfg[key]).is_absolute() and
                os.environ.get(variable) == cfg[key], "WORKER_HOST_CONFIGURATION_MISMATCH")
    require(Path(cfg["draft_store"]).is_file(), "WORKER_AUTHORITY_STORE_MISSING")
    runtime = compose_operator_runtime(ledger_path=cfg["ledger_path"], authorize_request=lambda _: False,
        read_transport=cfg["read_transport"], revocation_max_age_seconds=cfg["revocation_max_age_seconds"])
    with bind_operator_runtime(runtime):
        authority_from_host().authorize_invocation(command)
    # Dependency bootstrap runs only AFTER signed-command/revocation admission.
    writers = _adapter_factory() if (_adapter_factory is not None and
        command["mode"] == "execute_bound" and cfg["enabled_write_kinds"]) else {}
    runtime = compose_operator_runtime(ledger_path=cfg["ledger_path"], authorize_request=lambda _: False,
        read_transport=cfg["read_transport"], revocation_max_age_seconds=cfg["revocation_max_age_seconds"],
        writers=writers, enabled_write_kinds=frozenset(cfg["enabled_write_kinds"]))
    with bind_operator_runtime(runtime):
        yield runtime


def publish_worker_receipt(command, result):
    """Bounded result transport in the existing Prefect API, not a new service."""
    from prefect.client.orchestration import get_client
    from prefect.client.schemas.actions import ArtifactCreate
    receipt = {"schema": "IRONMAN_OPERATOR_RECEIPT_V1", "flow_run_id": current_invocation_id(),
               "command_sha256": digest(command), "worker_pid": os.getpid(), "result": result}
    require(len(json.dumps(receipt).encode()) <= 2_000_000, "WORKER_RESULT_TOO_LARGE")
    with get_client(sync_client=True) as client:
        client.create_artifact(ArtifactCreate(key="ironman-request-" + current_invocation_id(),
            type="result", data=receipt, flow_run_id=UUID(current_invocation_id())))
