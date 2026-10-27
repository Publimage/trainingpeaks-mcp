"""Host-only composition of MCP requests and the existing Prefect lifecycle.

No production binding, identity, writer or launcher is installed here. Trusted
transport middleware owns request admission; serialized tool arguments cannot
choose principals, callbacks, runtime paths or writer capabilities.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from tp_mcp.client.context import athlete_override

MODES = ("prepare", "preview_draft", "resume_preview", "approve_preview",
         "bind_execution", "revoke_approval", "execute_bound", "recover_worker")


@dataclass(frozen=True)
class OperatorBindings:
    """Code-installed dependencies. Missing bindings/capabilities deny.

    Request admission is separate from exact-preview review authority. The host
    hook runs inside the actual flow context, where its run ID is available.
    Writers require both installation and an explicit independent kind gate.
    """
    ledger_path: str
    authorize_request: Callable[[dict[str, Any]], bool]
    invoke_flow: Callable[..., dict[str, Any]]
    read_transport: str = "private_bridge"
    writers: Mapping[str, Any] = field(default_factory=dict)
    enabled_write_kinds: frozenset[str] = frozenset()
    on_flow_start: Callable[[str, dict[str, Any]], None] | None = None

    def __post_init__(self) -> None:
        if (not Path(self.ledger_path).is_absolute() or not callable(self.authorize_request)
                or not callable(self.invoke_flow)):
            raise ValueError("OPERATOR_HOST_CONFIGURATION_INVALID")
        object.__setattr__(self, "writers", MappingProxyType(dict(self.writers)))
        object.__setattr__(self, "enabled_write_kinds", frozenset(self.enabled_write_kinds))

    def execution_adapters(self, manifest: dict[str, Any]) -> Mapping[str, Any]:
        kinds = {item["kind"] for item in manifest["changes"]}
        if not kinds or not kinds <= self.enabled_write_kinds or not kinds <= self.writers.keys():
            raise PermissionError("OPERATOR_WRITER_CAPABILITY_NOT_ENABLED")
        return {kind: self.writers[kind] for kind in kinds}


_bindings: ContextVar[OperatorBindings | None] = ContextVar("ironman_operator_bindings", default=None)


def current_bindings(*, required: bool = False) -> OperatorBindings | None:
    result = _bindings.get()
    if required and result is None:
        raise PermissionError("OPERATOR_RUNTIME_NOT_CONFIGURED")
    return result


@contextmanager
def bind_operator_runtime(bindings: OperatorBindings) -> Iterator[None]:
    """Trusted host composition only; reset prevents cross-request leakage."""
    if not isinstance(bindings, OperatorBindings):
        raise TypeError("OPERATOR_HOST_CONFIGURATION_INVALID")
    token = _bindings.set(bindings)
    try:
        yield
    finally:
        _bindings.reset(token)


async def dispatch_operator_request(command: dict[str, Any]) -> dict[str, Any]:
    """MCP ingress to the existing flow; no alternative scheduler/provider."""
    if (type(command) is not dict or set(command) != {"mode", "manifest", "requested_targets"}
            or type(command.get("mode")) is not str or command["mode"] not in MODES
            or type(command.get("manifest")) is not dict
            or type(command.get("requested_targets")) is not list):
        return {"isError": True, "error_code": "OPERATOR_REQUEST_SHAPE"}
    if athlete_override.get() is not None:
        return {"isError": True, "error_code": "OPERATOR_ATHLETE_OVERRIDE_FORBIDDEN"}
    try:
        bindings = current_bindings(required=True)
        assert bindings is not None
        raw = json.dumps(command, allow_nan=False)
        if len(raw.encode()) > 2_000_000:
            return {"isError": True, "error_code": "OPERATOR_REQUEST_TOO_LARGE"}
        if bindings.authorize_request(json.loads(raw)) is not True:
            raise PermissionError("OPERATOR_REQUEST_UNAUTHORIZED")
        admitted = json.loads(raw)

        def invoke() -> dict[str, Any]:
            return bindings.invoke_flow(
                admitted["manifest"], bindings.ledger_path, mode=admitted["mode"],
                read_transport=bindings.read_transport,
                requested_targets=admitted["requested_targets"])

        return await asyncio.to_thread(invoke)
    except PermissionError:
        return {"isError": True, "error_code": "OPERATOR_REQUEST_DENIED"}
