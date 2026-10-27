"""Reusable, reviewed one-PDF retirement adapter for the IRONMAN ChangeSet V1.

This implements the already-verified native Training Plan Calendar Note attachment
DELETE operation. Neither the plan nor the attachment ID is fixed in code.
The default is READ/VALIDATE ONLY: the real writer is NOT enabled by the
existing unified Prefect preview flow. A separately approved writer must be
injected explicitly after the Proven Paths gate and its disposable-plan canary.

The common changeset ledger, lock, approval gate, drift check, and readback own
idempotency. Never replay an ambiguous destructive request automatically.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, cast, Callable

from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    OWNER, ChangeStop, SecurityDenied, WriteUncertain, digest, need,
)
from scripts.ironman_jobs.ironman_unified_trainingpeaks_reads import (
    TrainingPeaksReadOnlyAdapter,
)


def validate_pdf_retirement(change: dict[str, Any], note: dict[str, Any]) -> tuple[int, int, int]:
    """Demand that the approved after-image differs by ONE exact PDF only."""
    need(change.get("kind") == "plan.note.attachment.retire", "NOT_PDF_RETIRE_KIND")
    target = change.get("target")
    need(isinstance(target, dict) and target.get("provider") == "trainingpeaks"
         and target.get("owner_id") == OWNER
         and target.get("container_kind") == "training_plan", "PDF_RETIRE_TARGET")
    plan_id, note_id = target.get("container_id"), target.get("resource_id")
    need(type(plan_id) is int and plan_id > 0
         and type(note_id) is int and note_id > 0, "PDF_RETIRE_IDS")
    need(type(note) is dict and note.get("planId") == plan_id
         and note.get("id") == note_id, "PDF_RETIRE_NOTE_IDENTITY")
    payload = change.get("payload")
    need(type(payload) is dict and set(payload) == {
        "desired", "attachment_id", "expected_file_name", "expected_content_length"
    }, "PDF_RETIRE_PAYLOAD_FIELDS")
    payload = cast(dict[str, Any], payload)
    target_id = payload["attachment_id"]
    need(type(target_id) is int and target_id > 0, "PDF_RETIRE_ATTACHMENT_ID")
    filename, length = payload["expected_file_name"], payload["expected_content_length"]
    need(type(filename) is str and filename.lower().endswith(".pdf")
         and type(length) is int and length > 100, "PDF_RETIRE_FILE_IDENTITY")
    current = note.get("attachments")
    need(type(current) is list and bool(current), "PDF_RETIRE_INVENTORY_REQUIRED")
    current = cast(list[dict[str, Any]], current)
    ids = [row.get("id") for row in current if type(row) is dict]
    need(len(ids) == len(current) and all(type(i) is int for i in ids)
         and len(set(ids)) == len(ids), "PDF_RETIRE_AMBIGUOUS_INVENTORY")
    matches = [row for row in current if row["id"] == target_id]
    need(len(matches) == 1, "PDF_RETIRE_TARGET_NOT_PRESENT")
    found = matches[0]
    need(found.get("fileName") == filename
         and found.get("contentLength") == length,
         "PDF_RETIRE_FILE_CHANGED")
    if "contentType" in found:
        need(found["contentType"] == "application/pdf", "PDF_RETIRE_NOT_PDF")
    desired = payload["desired"]
    need(type(desired) is dict, "PDF_RETIRE_DESIRED_NOT_OBJECT")
    safe_after = deepcopy(note)
    safe_after["attachments"] = [row for row in current if row["id"] != target_id]
    need(desired == safe_after, "PDF_RETIRE_OTHER_FIELD_CHANGED")
    need(change.get("before_sha256") == digest(note)
         and change.get("after_sha256") == digest(desired),
         "PDF_RETIRE_REVIEW_HASH_DRIFT")
    return plan_id, note_id, target_id


class ReviewedNotePdfRetireAdapter:
    """One type adapter for ANY coach-owned plan and note ID.

    The default has NO write capability. The callable `delete_one` must be
    explicitly supplied by a reviewed publisher; it has no retries and must
    raise on provider errors. The unified engine re-reads after ANY error.
    """
    def __init__(self, *, reader: Any = None,
                 delete_one: Callable[[int, int, int], None] | None = None):
        self.reader = reader if reader is not None else TrainingPeaksReadOnlyAdapter()
        self.delete_one = delete_one

    def read(self, change: dict[str, Any]) -> dict[str, Any]:
        return self.reader.read(change)

    def validate(self, change: dict[str, Any], current: dict[str, Any]) -> None:
        # Shared engine invokes this in preview as well as before a write.
        validate_pdf_retirement(change, current)

    def apply(self, change: dict[str, Any]) -> None:
        if self.delete_one is None:
            raise SecurityDenied("PDF_RETIRE_WRITER_NOT_ACTIVATED")
        # Re-read immediately before the destructive call. This prevents a
        # direct caller from skipping preimage and attachment preservation.
        current = self.read(change)
        plan_id, note_id, attachment_id = validate_pdf_retirement(change, current)
        # Exactly one provider mutation. Timeout/uncertainty is reconciled by
        # the common ChangeSet engine, never by a blind in-adapter retry.
        self.delete_one(plan_id, note_id, attachment_id)


async def proven_path_delete_one_pdf(plan_id: int, note_id: int, attachment_id: int) -> None:
    """Existing 2026-10-19 DELETE endpoint, not a new network/provider path.

    This function is NOT wired into create_read_registry or the Prefect flow.
    Integrators must deliberately review/authorize a writer before injection.
    """
    from tp_mcp.client import TPClient

    need(all(type(v) is int and v > 0 for v in (plan_id, note_id, attachment_id)),
         "PDF_RETIRE_INVALID_PROVIDER_IDS")
    async with TPClient() as client:
        identity = await client._get_user_data()
        need(type(identity) is dict and identity.get("personId") == OWNER,
             "PDF_RETIRE_WRONG_COACH")
        response = await client._request(
            "DELETE",
            f"/plans/v1/plans/{plan_id}/calendarNote/{note_id}/attachments/{attachment_id}",
            _retry_on_401=False,
        )
        if response.is_error:
            status = getattr(response, "status_code", None)
            if status in (401, 403):
                raise SecurityDenied("PDF_RETIRE_PROVIDER_AUTH_DENIED")
            raise WriteUncertain("PDF_RETIRE_PROVIDER_DELETE_UNCERTAIN")


def proven_path_delete_one_pdf_sync(plan_id: int, note_id: int, attachment_id: int) -> None:
    """Synchronous bridge for a future explicitly approved TP-host adapter."""
    asyncio.run(proven_path_delete_one_pdf(plan_id, note_id, attachment_id))