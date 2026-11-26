"""Fixed-scope acceptance of the complete-copy tool on Piattaforma TEST.

No CLI-selected resources, routes, dates, or filesystem paths. Preview and verify
cannot mutate TrainingPeaks. Execute retains its receipt before the first create
so a terminated operator process resumes the same request, never a fresh copy.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from tp_mcp.tools.plan_transfer import _state_directory
from tp_mcp.tools.plan_transfer_core import (
    PlanSnapshot,
    TransferError,
    TransferItem,
    TransferRequest,
    _persist,
    preview,
    transfer,
)
from tp_mcp.tools.plan_transfer_provider import TrainingPeaksTransferGateway

SOURCE_PLAN_ID = 689369
ATHLETE_ID = 941614
ATHLETE_NAME = "Piattaforma TEST"
START_DATE = "2028-01-03"
VISIBLE_THROUGH = "2028-01-16"
REQUEST_ID = "complete-plan-transfer-winter-test-v1"
DAY_COUNT = 56
COUNTS = {"classic": 58, "strength": 16, "note": 9, "attachment": 1}
OUTSIDE_WINDOWS = (("2027-12-27", "2028-01-02"), ("2028-02-28", "2028-03-05"))
RECEIPT_SCHEMA = "COMPLETE_PLAN_TRANSFER_LAB_V1"


def _need(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise TransferError(code, message)


def _request(digest: str | None = None) -> TransferRequest:
    return TransferRequest(REQUEST_ID, SOURCE_PLAN_ID, ATHLETE_ID, START_DATE, VISIBLE_THROUGH, digest)


def _scope(request: TransferRequest) -> None:
    _need(replace(request, expected_source_digest=None) == _request(),
          "LAB_SCOPE_MISMATCH", "This acceptance job only targets the fixed test athlete and dates.")


class LabGateway(TrainingPeaksTransferGateway):
    async def preflight(self, request: TransferRequest) -> PlanSnapshot:
        self._lab_ready_request: TransferRequest | None = None
        _scope(request)
        snapshot = await super().preflight(request)
        _need(self.athlete_name == ATHLETE_NAME, "LAB_ATHLETE_NAME_MISMATCH", "Test athlete identity changed.")
        _need(snapshot.plan_id == SOURCE_PLAN_ID and snapshot.day_count == DAY_COUNT
              and Counter(item.kind for item in snapshot.items) == COUNTS,
              "LAB_SOURCE_SHAPE_MISMATCH", "Winter source counts or 56-day span differ from the approved lab case.")
        self._lab_ready_request = request
        return snapshot

    async def create(self, request: TransferRequest, item: TransferItem, target_date: str,
                     hidden: bool, parent_target_id: str | None) -> str:
        _scope(request)
        _need(getattr(self, "_lab_ready_request", None) == request,
              "LAB_PREFLIGHT_REQUIRED", "The fixed test target must pass preflight before any create.")
        return await super().create(request, item, target_date, hidden, parent_target_id)


class VerifyLabGateway(LabGateway):
    async def create(self, request: TransferRequest, item: TransferItem, target_date: str,
                     hidden: bool, parent_target_id: str | None) -> str:
        self.create_attempts = getattr(self, "create_attempts", 0) + 1
        raise TransferError("LAB_VERIFY_WRITE_BLOCKED", "The verification job cannot create provider objects.")


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _identity(row: Any, *keys: str) -> str:
    _need(isinstance(row, dict), "LAB_OUTSIDE_READ_INVALID", "Outside-range object is malformed.")
    values = {str(row[k]) for k in keys if row.get(k) is not None}
    _need(len(values) == 1, "LAB_OUTSIDE_READ_INVALID", "Outside-range identity is ambiguous.")
    value = values.pop()
    _need(value.isdigit() and int(value) > 0, "LAB_OUTSIDE_READ_INVALID", "Outside-range identity is invalid.")
    return value


def _rows(rows: Any) -> list[dict[str, Any]]:
    _need(type(rows) is list and all(type(r) is dict for r in rows),
          "LAB_OUTSIDE_READ_INVALID", "Complete outside-range inventory is required.")
    return rows


def _outside_day(row: dict[str, Any], start: str, end: str, *keys: str) -> None:
    value = next((row[k] for k in keys if row.get(k) is not None), None)
    if not isinstance(value, str) or len(value) < 10:
        raise TransferError("LAB_OUTSIDE_READ_INVALID", "Outside-range date is unreadable.")
    try:
        day = date.fromisoformat(value[:10])
    except ValueError as exc:
        raise TransferError("LAB_OUTSIDE_READ_INVALID", "Outside-range date is invalid.") from exc
    _need(date.fromisoformat(start) <= day <= date.fromisoformat(end),
          "LAB_OUTSIDE_READ_INVALID", "Outside-range endpoint returned an unexpected date.")


async def _outside_digest(gateway: LabGateway) -> str:
    """Hash adjacent calendar records, including complete native strength details.

Only the digest is persisted. Calendar notes include their attachment metadata;
this check does not download PDFs belonging to unrelated outside-range notes.
"""
    windows = []
    for start, end in OUTSIDE_WINDOWS:
        classic = _rows(await gateway._get(f"/fitness/v6/athletes/{ATHLETE_ID}/workouts/{start}/{end}", list))
        notes = _rows(await gateway._get(f"/fitness/v2/athletes/{ATHLETE_ID}/calendarNote/{start}/{end}", list))
        native_end = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        summaries = _rows(await gateway._native(
            "GET", f"/rx/activity/v1/workouts/calendar/{ATHLETE_ID}/{start}/{native_end}"))
        native = []
        for row in classic:
            _identity(row, "workoutId", "id")
            _need(row.get("athleteId") == ATHLETE_ID, "LAB_OUTSIDE_IDENTITY", "Outside workout athlete differs.")
            _outside_day(row, start, end, "workoutDay")
        for row in notes:
            _identity(row, "id", "calendarNoteId", "noteId")
            _need(row.get("athleteId", ATHLETE_ID) == ATHLETE_ID,
                  "LAB_OUTSIDE_IDENTITY", "Outside note athlete differs.")
            _outside_day(row, start, end, "noteDate", "date")
        for summary in summaries:
            wid = _identity(summary, "id", "workoutId")
            detail = await gateway._native("GET", f"/rx/activity/v1/workouts/{wid}")
            _need(_identity(detail, "id", "workoutId") == wid and detail.get("calendarId") == ATHLETE_ID,
                  "LAB_OUTSIDE_IDENTITY", "Outside native workout identity differs.")
            _outside_day(detail, start, end, "prescribedDate")
            native.append(detail)
        groups = ((classic, ("workoutId", "id")), (notes, ("id", "calendarNoteId", "noteId")),
                  (native, ("id", "workoutId")))
        for rows, keys in groups:
            identities = [_identity(row, *keys) for row in rows]
            _need(len(identities) == len(set(identities)), "LAB_OUTSIDE_READ_INVALID", "Duplicate outside identity.")
            rows.sort(key=lambda row: _identity(row, *keys))
        windows.append({"start": start, "end": end, "classic": classic, "notes": notes, "strength": native})
    return hashlib.sha256(_json(windows).encode()).hexdigest()


def _receipt_path() -> Path:
    return _state_directory() / "lab-acceptance" / "winter-test-v1.json"


def _read_receipt() -> dict[str, Any] | None:
    path = _receipt_path()
    _need(not any(p.is_symlink() for p in (path, *path.parents)),
          "LAB_RECEIPT_UNSAFE", "Receipt paths cannot contain symbolic links.")
    if not path.exists():
        return None
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, ValueError) as exc:
        raise TransferError("LAB_RECEIPT_INVALID", "Lab receipt could not be read.") from exc
    _need(isinstance(value, dict) and value.get("schema") == RECEIPT_SCHEMA
          and value.get("request_id") == REQUEST_ID and value.get("source_plan_id") == SOURCE_PLAN_ID
          and value.get("athlete_id") == ATHLETE_ID and value.get("start_date") == START_DATE
          and value.get("visible_through") == VISIBLE_THROUGH and value.get("day_count") == DAY_COUNT,
          "LAB_RECEIPT_MISMATCH", "Existing lab receipt belongs to a different scope.")
    for key in ("source_digest", "outside_before"):
        _need(type(value.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}", value[key]) is not None,
              "LAB_RECEIPT_INVALID", "Lab receipt lacks a valid source or outside-range digest.")
    return value


def _save_receipt(receipt: dict[str, Any]) -> None:
    path = _receipt_path()
    _need(not any(p.is_symlink() for p in (path, *path.parents)),
          "LAB_RECEIPT_UNSAFE", "Receipt paths cannot contain symbolic links.")
    _state_directory().mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.mkdir(exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    _persist(path, receipt)


def _emit(stage: str, result: dict[str, Any]) -> dict[str, Any]:
    output = {"stage": stage, "status": result.get("status"), "request_id": REQUEST_ID,
              "source_plan_id": SOURCE_PLAN_ID, "athlete_id": ATHLETE_ID,
              "counts": result.get("counts"), "create_calls_this_run": result.get("create_calls_this_run", 0),
              "verified_ids_count": len(result.get("created_ids", {}))}
    for key in ("ready", "source_digest", "error_code", "next_step", "source_verified", "outside_verified",
                "create_attempts"):
        if key in result:
            output[key] = result[key]
    if result.get("status") not in ("PREVIEW", "DONE_VERIFIED"):
        output["created_ids"] = result.get("created_ids", {})
        output["unverified_ids"] = result.get("unverified_ids", {})
    print(_json(output), flush=True)
    return result


async def run_preview() -> dict[str, Any]:
    async with VerifyLabGateway() as gateway:
        result = await preview(_request(), gateway)
        result["create_attempts"] = getattr(gateway, "create_attempts", 0)
        _need(result["create_attempts"] == 0, "LAB_PREVIEW_WRITE_ATTEMPT", "Preview attempted a provider mutation.")
        return _emit("COMPLETE_PLAN_TRANSFER_LAB_PREVIEW", result)


async def run_execute() -> dict[str, Any]:
    receipt = _read_receipt()
    async with LabGateway() as gateway:
        fresh = await preview(_request(), gateway)
        digest = fresh["source_digest"]
        outside_before = await _outside_digest(gateway)
        if receipt is None:
            _need(fresh.get("ready") is True, "LAB_TARGET_OCCUPIED",
                  "First lab execution requires an empty test range.")
            receipt = {"schema": RECEIPT_SCHEMA, "request_id": REQUEST_ID, "source_plan_id": SOURCE_PLAN_ID,
                       "athlete_id": ATHLETE_ID, "start_date": START_DATE, "visible_through": VISIBLE_THROUGH,
                       "day_count": DAY_COUNT, "source_digest": digest, "outside_before": outside_before,
                       "status": "PREPARED", "result": None}
            _save_receipt(receipt)
        else:
            _need(receipt["source_digest"] == digest, "LAB_SOURCE_CHANGED",
                  "Source differs from the original lab receipt.")
            _need(receipt["outside_before"] == outside_before,
                  "LAB_OUTSIDE_DRIFT", "Adjacent calendar data changed; inspect before resuming.")
        try:
            result = await transfer(_request(digest), gateway, _state_directory(), execute=True)
        except TransferError as exc:
            result = dict(exc.progress or {})
            result.update(status="BLOCKED", error_code=exc.code,
                          next_step="Inspect this request's receipt and provider state; do not start another copy.")
        receipt.update(status="TRANSFER_DONE_OUTSIDE_PENDING" if result["status"] == "DONE_VERIFIED"
                       else result["status"], result=result)
        _save_receipt(receipt)
        # Persist the transfer outcome before the independent outside check.
        try:
            outside_after = await _outside_digest(gateway)
        except Exception:
            result.update(status="BLOCKED", error_code="LAB_OUTSIDE_UNVERIFIED", outside_verified=False,
                          next_step="Read adjacent calendar state before accepting or resuming the lab run.")
            receipt.update(status=result["status"], result=result)
            _save_receipt(receipt)
            return _emit("COMPLETE_PLAN_TRANSFER_LAB_EXECUTE", result)
        receipt["outside_after"] = outside_after
        result["outside_verified"] = outside_after == receipt["outside_before"]
        result["source_verified"] = result.get("status") == "DONE_VERIFIED"
        if not result["outside_verified"]:
            result.update(status="BLOCKED", error_code="LAB_OUTSIDE_DRIFT",
                          next_step="Inspect adjacent calendar data; the driver will not repeat or roll back the copy.")
        receipt.update(status=result["status"], result=result)
        _save_receipt(receipt)
        return _emit("COMPLETE_PLAN_TRANSFER_LAB_EXECUTE", result)


async def run_verify() -> dict[str, Any]:
    receipt = _read_receipt()
    if receipt is None:
        raise TransferError("LAB_COMPLETED_RECEIPT_REQUIRED", "Verify requires the completed original lab receipt.")
    _need(receipt.get("status") == "DONE_VERIFIED"
          and isinstance(receipt.get("result"), dict) and receipt["result"].get("status") == "DONE_VERIFIED",
          "LAB_COMPLETED_RECEIPT_REQUIRED", "Verify requires the completed original lab receipt.")
    async with VerifyLabGateway() as gateway:
        request = _request(receipt["source_digest"])
        await gateway.preflight(request)
        outside_before = await _outside_digest(gateway)
        _need(outside_before == receipt["outside_before"], "LAB_OUTSIDE_DRIFT", "Adjacent calendar data changed.")
        result = await transfer(request, gateway, _state_directory(), execute=True)
        attempts = getattr(gateway, "create_attempts", 0)
        _need(attempts == 0 and result.get("create_calls_this_run") == 0 and result.get("status") == "DONE_VERIFIED",
              "LAB_REPLAY_FAILED", "Replay did not verify a read-only result; provider creates were blocked.")
        _need(result.get("created_ids") == receipt["result"].get("created_ids"),
              "LAB_RECEIPT_IDS_CHANGED", "Verified destination identities differ from the original receipt.")
        outside_after = await _outside_digest(gateway)
        _need(outside_after == outside_before, "LAB_OUTSIDE_DRIFT",
              "Adjacent calendar data changed during verification.")
        result.update(create_attempts=attempts, source_verified=True, outside_verified=True)
        return _emit("COMPLETE_PLAN_TRANSFER_LAB_VERIFY", result)


def main(mode: str) -> None:
    try:
        _need(len(sys.argv) == 1, "LAB_ARGUMENTS_NOT_ALLOWED", "This job accepts no command-line arguments.")
        functions = {"preview": run_preview, "execute": run_execute, "verify": run_verify}
        _need(mode in functions, "LAB_MODE_INVALID", "Unknown acceptance stage.")
        result = asyncio.run(functions[mode]())
        raise SystemExit(0 if result.get("status") in ("PREVIEW", "DONE_VERIFIED") else 2)
    except TransferError as exc:
        _emit("COMPLETE_PLAN_TRANSFER_LAB_STOP", {
            **(exc.progress or {}), "status": "BLOCKED", "error_code": exc.code,
            "next_step": "Inspect the existing receipt; retain the same request ID. No automatic rollback.",
        })
        raise SystemExit(2) from None
    except Exception:
        _emit("COMPLETE_PLAN_TRANSFER_LAB_STOP", {
            "status": "UNVERIFIED", "error_code": "LAB_INTERRUPTED",
            "next_step": "Inspect the existing receipt and provider state; retain the same request ID.",
        })
        raise SystemExit(2) from None
