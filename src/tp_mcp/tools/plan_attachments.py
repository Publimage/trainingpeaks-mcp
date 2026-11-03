"""Upload a verified PDF to a native TrainingPeaks Training Plan calendar note.

Only an exact coach-owned plan/note is eligible. The PDF comes from a temporary
signed OpenAI file download URL passed at call time; no file bytes or signed
URL are persisted in GitHub, plan descriptions, source manifests or logs.
Uses provider route proven by Chasing / Intermediate PDF attachment jobs.
"""
from __future__ import annotations

import base64
import hashlib
import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from tp_mcp.client import TPClient

OWNER = 2116886
MAX_PDF_BYTES = 10 * 1024 * 1024


def _error(code: str, message: str) -> dict[str, Any]:
    return {"success": False, "error_code": code, "message": message}


def _allowed_source(url: str) -> bool:
    try:
        u = urlsplit(url)
        return (
            u.scheme == "https"
            and u.username is None and u.password is None and u.port is None
            and re.fullmatch(r"sdmntpr[a-z0-9-]+\.oaiusercontent\.com", u.hostname or "") is not None
            and re.fullmatch(r"/files/[0-9a-f-]+/raw", u.path) is not None
            and u.query != ""
            and u.fragment == ""
        )
    except (ValueError, TypeError):
        return False


def _note_id(note: dict[str, Any]) -> int:
    return int(note.get("id") or note.get("calendarNoteId") or note.get("noteId") or 0)


async def tp_attach_training_plan_note_pdf(
    plan_id: int, note_id: int, file_name: str, source_url: str,
    expected_sha256: str, expected_size_bytes: int,
) -> dict[str, Any]:
    """Upload binary PDF to one existing native note, with protected readback."""
    if (not isinstance(plan_id, int) or not isinstance(note_id, int)
        or isinstance(plan_id, bool) or isinstance(note_id, bool)
        or plan_id <= 0 or note_id <= 0):
        return _error("VALIDATION_ERROR", "Invalid plan or note ID.")
    if (not isinstance(file_name, str) or not file_name.lower().endswith(".pdf")
        or "/" in file_name or "\\" in file_name or not 1 <= len(file_name) <= 180):
        return _error("VALIDATION_ERROR", "File name must be a PDF basename.")
    if (not isinstance(expected_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256.lower()) is None
        or not isinstance(expected_size_bytes, int) or isinstance(expected_size_bytes, bool)
        or not 100 <= expected_size_bytes <= MAX_PDF_BYTES):
        return _error("VALIDATION_ERROR", "Invalid expected SHA256 or file size.")
    if not _allowed_source(source_url):
        return _error("PROTECTED_RESOURCE", "Source must be a temporary trusted file URL.")

    async with TPClient() as client:
        me = await client._get_user_data()
        if not isinstance(me, dict) or me.get("personId") != OWNER:
            return _error("PROTECTED_RESOURCE", "Authenticated coach owner mismatch.")
        owned = await client.get("/plans/v1/plans")
        if owned.is_error or not isinstance(owned.data, list) or not any(
            p.get("planId") == plan_id for p in owned.data
        ):
            return _error("PROTECTED_RESOURCE", "Target plan not coach-owned.")
        response = await client.get(f"/plans/v1/plans/{plan_id}")
        if response.is_error or not isinstance(response.data, dict):
            return _error("API_ERROR", "Unable to verify target plan metadata.")
        plan = response.data
        if plan.get("planId") != plan_id:
            return _error("PROTECTED_RESOURCE", "Plan identity mismatch.")
        try:
            technical_start = date.fromisoformat(str(plan["startDate"])[:10])
            start = technical_start - timedelta(days=technical_start.weekday())
            week_count = int(plan["weekCount"])
            end = start + timedelta(days=max(7 * week_count, int(plan.get("dayCount") or 0)) + 1)
        except (ValueError, TypeError, KeyError):
            return _error("API_ERROR", "Plan has no verifiable relative calendar.")

        async def all_notes() -> list[dict[str, Any]] | None:
            r = await client.get(
                f"/plans/v1/plans/{plan_id}/calendarNote/"
                f"{start.isoformat()}/{end.isoformat()}"
            )
            return r.data if not r.is_error and isinstance(r.data, list) else None

        before = await all_notes()
        if before is None:
            return _error("API_ERROR", "Cannot read native notes.")
        target = next((n for n in before if _note_id(n) == note_id), None)
        if target is None:
            return _error("NOT_FOUND", "Note ID not present on target plan.")
        old = target.get("attachments") or []
        if not isinstance(old, list) or len(old) >= 15:
            return _error("PROTECTED_RESOURCE", "Unsupported attachment inventory.")
        for attachment in old:
            if attachment.get("fileName") == file_name:
                if int(attachment.get("contentLength") or -1) != expected_size_bytes:
                    return _error("CONFLICT", "Existing file name has a different size.")
                return {
                    "success": True, "already_present": True, "readback_verified": True,
                    "plan_id": plan_id, "note_id": note_id,
                    "attachment_id": attachment.get("id"), "file_name": file_name,
                    "content_length": expected_size_bytes,
                }

        # Download source exactly once before POST. No redirects, strict byte/hash gate.
        try:
            async with httpx.AsyncClient(follow_redirects=False, timeout=45) as hc:
                download = await hc.get(source_url)
            if download.status_code != 200:
                return _error("SOURCE_UNAVAILABLE", "Signed PDF source is unavailable.")
            blob = download.content
        except Exception:
            return _error("SOURCE_UNAVAILABLE", "Signed PDF download failed.")
        if (len(blob) != expected_size_bytes
            or not blob.startswith(b"%PDF-")
            or hashlib.sha256(blob).hexdigest() != expected_sha256.lower()):
            return _error("SOURCE_MISMATCH", "PDF binary failed size/signature/hash validation.")

        await client._ensure_client()
        token = await client._ensure_access_token()
        if not token.success:
            return _error("AUTH_MISSING", "TrainingPeaks authentication missing.")
        payload = {
            "planId": plan_id, "noteId": note_id, "fileName": file_name,
            "contentType": "application/pdf",
            "data": base64.b64encode(blob).decode("ascii"),
        }
        ambiguous = False
        status = None
        try:
            result = await client._client.request(
                "POST",
                f"{client.base_url}/plans/v1/plans/{plan_id}/calendarNote/{note_id}/attachments",
                headers=client._get_headers(), json=payload, timeout=60,
            )
            status = result.status_code
        except Exception:
            ambiguous = True

        after = await all_notes()
        if after is None:
            return _error("WRITE_UNVERIFIED", "Attachment POST outcome uncertain; do not retry blindly.")
        final = next((n for n in after if _note_id(n) == note_id), None)
        if final is None or len(after) != len(before) or {
            _note_id(n) for n in after
        } != {_note_id(n) for n in before}:
            return _error("WRITE_UNVERIFIED", "Native notes inventory changed; inspect provider.")
        baseline_other = {_note_id(n): n for n in before if _note_id(n) != note_id}
        if any(n != baseline_other.get(_note_id(n)) for n in after if _note_id(n) != note_id):
            return _error("WRITE_UNVERIFIED", "Unexpected change in another note.")
        if {k:v for k,v in final.items() if k != "attachments"} != {
            k:v for k,v in target.items() if k != "attachments"
        }:
            return _error("WRITE_UNVERIFIED", "Note content changed unexpectedly.")
        current = final.get("attachments") or []
        match = [
            a for a in current
            if a.get("fileName") == file_name
            and int(a.get("contentLength") or -1) == expected_size_bytes
            and a.get("id") is not None
        ]
        if len(match) != 1 or len(current) != len(old) + 1:
            return _error(
                "WRITE_UNVERIFIED" if ambiguous or status in (200, 201, 204) else "PROVIDER_REJECTED",
                "Native PDF attachment not verified; inspect before retry.",
            )
        after_plan = await client.get(f"/plans/v1/plans/{plan_id}")
        if after_plan.is_error or any(
            after_plan.data.get(k) != plan.get(k)
            for k in ("planId", "title", "workoutCount", "weekCount", "isPublic", "price")
        ):
            return _error("WRITE_UNVERIFIED", "Plan metadata changed or could not be verified.")
        return {
            "success": True, "readback_verified": True, "already_present": False,
            "plan_id": plan_id, "note_id": note_id,
            "attachment_id": match[0]["id"], "file_name": file_name,
            "content_length": expected_size_bytes,
            "sha256": expected_sha256.lower(),
            "note_count": len(after), "workout_count": plan.get("workoutCount"),
        }
