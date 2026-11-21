"""Public entry point for complete, independently verified plan copies.

The old laboratory apply tool and the HTTP prohibition on native apply remain
unchanged. This capability creates independent calendar objects and keeps its
receipt on the existing MCP host; it never removes an applied/source plan.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from tp_mcp.tools.plan_transfer_core import TransferError, TransferRequest, transfer
from tp_mcp.tools.plan_transfer_provider import TrainingPeaksTransferGateway


def _state_directory() -> Path:
    # Not caller configurable: a tool argument must not select a server path.
    return Path.home() / ".local" / "share" / "tp-mcp" / "plan-transfers"


async def tp_copy_training_plan_to_athlete(
    plan_id: int,
    athlete_id: int,
    start_date: str,
    request_id: str,
    visible_through: str | None = None,
    expected_source_digest: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview, execute or resume a complete plan copy using the same request ID.

    Preview is the default and performs no provider writes. Execution requires
    the source digest returned by preview. An occupied destination range, source
    drift or an uncertain unmatched creation blocks further writes. Repeating
    the same completed request verifies its receipt instead of copying again.
    ``visible_through=None`` means that the entire copied block is visible.
    """
    if type(execute) is not bool:
        return {"isError": True, "success": False, "error_code": "INVALID_EXECUTE",
                "message": "execute must be a boolean."}
    request = TransferRequest(
        request_id=request_id,
        source_plan_id=plan_id,
        athlete_id=athlete_id,
        start_date=start_date,
        visible_through=visible_through,
        expected_source_digest=expected_source_digest,
    )
    try:
        async with TrainingPeaksTransferGateway() as gateway:
            result = await transfer(request, gateway, _state_directory(), execute=execute)
            result.update({
                "success": result.get("status") in {"PREVIEW", "DONE_VERIFIED"},
                "copy_mode": "independent_calendar_objects",
                "linked_plan_application": False,
                "athlete_id": athlete_id,
                "source_plan_id": plan_id,
                "request_id": request_id,
            })
            if result.get("status") == "UNCERTAIN":
                result["isError"] = True
            return result
    except TransferError as exc:
        result = dict(getattr(exc, "progress", None) or {})
        result.update({"isError": True, "success": False, "error_code": exc.code,
                       "message": str(exc), "request_id": request_id})
        return result
    except Exception:
        # Do not expose credentials, raw provider responses or private content.
        # The journal retains any intent written before an uncertain mutation.
        return {
            "isError": True, "success": False, "error_code": "TRANSFER_UNVERIFIED",
            "message": "Transfer interrupted. Reconcile using the same request ID; do not start a new copy.",
            "request_id": request_id,
        }
