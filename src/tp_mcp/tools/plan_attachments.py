"""Upload verified PDF files to native TrainingPeaks plan and athlete calendar notes.

Only an exact coach-owned plan/note or roster-verified athlete note is eligible. The PDF comes from a temporary
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


async def tp_attach_native_note_pdf(
    target_type: str,
    target_id: int,
    note_id: int,
    file_name: str,
    source_url: str,
    expected_sha256: str,
    expected_size_bytes: int,
    expected_note_date: str | None = None,
    expected_note_title: str | None = None,
) -> dict[str, Any]:
    """Attach a PDF to an existing native plan or athlete note.

    One shared upload implementation; plan and athlete resources have separate
    identity/preflight rules. No create/delete/overwrite or blind POST retries.
    The source URL is never logged or persisted.
    """
    if target_type not in ("plan", "athlete"):
        return _error("VALIDATION_ERROR", "target_type must be 'plan' or 'athlete'.")
    if (not isinstance(target_id, int) or isinstance(target_id, bool) or target_id <= 0
        or not isinstance(note_id, int) or isinstance(note_id, bool) or note_id <= 0):
        return _error("VALIDATION_ERROR", "Invalid target or note ID.")
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
    if target_type == "athlete":
        if not isinstance(expected_note_title, str) or not expected_note_title.strip():
            return _error("VALIDATION_ERROR", "Athlete note title is required.")
        try:
            if expected_note_date is None:
                raise ValueError("missing date")
            date.fromisoformat(expected_note_date)
        except ValueError:
            return _error("VALIDATION_ERROR", "Athlete note date must be YYYY-MM-DD.")

    async with TPClient() as client:
        # Read the provider user record fresh: do not trust the connector's
        # legacy process-global roster cache when selecting a new athlete.
        user_response = await client.get("/users/v3/user")
        if user_response.is_error or not isinstance(user_response.data, dict):
            return _error("API_ERROR", "Cannot verify current TrainingPeaks identity.")
        me = user_response.data.get("user", user_response.data)
        if not isinstance(me, dict) or me.get("personId") != OWNER:
            return _error("PROTECTED_RESOURCE", "Authenticated coach owner mismatch.")

        plan = None
        if target_type == "plan":
            owned = await client.get("/plans/v1/plans")
            if owned.is_error or not isinstance(owned.data, list) or not any(
                p.get("planId") == target_id for p in owned.data
            ):
                return _error("PROTECTED_RESOURCE", "Target plan not coach-owned.")
            response = await client.get(f"/plans/v1/plans/{target_id}")
            if response.is_error or not isinstance(response.data, dict):
                return _error("API_ERROR", "Unable to verify target plan metadata.")
            plan = response.data
            if plan.get("planId") != target_id:
                return _error("PROTECTED_RESOURCE", "Plan identity mismatch.")
            try:
                technical_start = date.fromisoformat(str(plan["startDate"])[:10])
                start = technical_start - timedelta(days=technical_start.weekday())
                week_count = int(plan["weekCount"])
                end = start + timedelta(days=max(7 * week_count, int(plan.get("dayCount") or 0)) + 1)
            except (ValueError, TypeError, KeyError):
                return _error("API_ERROR", "Plan has no verifiable relative calendar.")
            notes_url = (f"/plans/v1/plans/{target_id}/calendarNote/"
                         f"{start.isoformat()}/{end.isoformat()}")
            attachment_url = f"/plans/v1/plans/{target_id}/calendarNote/{note_id}/attachments"
        else:
            # A tag-only membership with name=null is NOT proof of coach authority.
            roster = me.get("athletes")
            if not isinstance(roster, list) or len([
                a for a in roster if isinstance(a, dict)
                and a.get("athleteId") == target_id
                and (str(a.get("firstName") or "").strip() or str(a.get("lastName") or "").strip())
            ]) != 1:
                return _error("PROTECTED_RESOURCE", "Athlete not uniquely identified in current coach roster.")
            notes_url = (f"/fitness/v2/athletes/{target_id}/calendarNote/"
                         f"{expected_note_date}/{expected_note_date}")
            attachment_url = f"/fitness/v1/athletes/{target_id}/calendarNote/{note_id}/attachments"

        async def all_notes() -> list[dict[str, Any]] | None:
            response = await client.get(notes_url)
            return response.data if not response.is_error and isinstance(response.data, list) else None

        before = await all_notes()
        if before is None:
            return _error("API_ERROR", "Cannot read native notes.")
        selected = [n for n in before if _note_id(n) == note_id]
        if len(selected) != 1:
            return _error("NOT_FOUND", "Note ID not uniquely present on target.")
        target = selected[0]
        if expected_note_title is not None and target.get("title") != expected_note_title:
            return _error("CONFLICT", "Note title mismatch.")
        if expected_note_date is not None and not str(
            target.get("noteDate") or target.get("date") or ""
        ).startswith(expected_note_date):
            return _error("CONFLICT", "Note date mismatch.")
        if target_type == "athlete":
            # Independent endpoint read protects against a stale range result.
            detail = await client.get(f"/fitness/v1/athletes/{target_id}/calendarNote/{note_id}")
            if (detail.is_error or not isinstance(detail.data, dict)
                or _note_id(detail.data) != note_id
                or detail.data.get("title") != target.get("title")
                or not str(detail.data.get("noteDate") or detail.data.get("date") or "")
                       .startswith(expected_note_date)):
                return _error("PROTECTED_RESOURCE", "Athlete note identity not confirmed.")

        old = target.get("attachments") or []
        if not isinstance(old, list) or len(old) >= 15:
            return _error("PROTECTED_RESOURCE", "Unsupported attachment inventory.")
        for attachment in old:
            if attachment.get("fileName") == file_name:
                if int(attachment.get("contentLength") or -1) != expected_size_bytes:
                    return _error("CONFLICT", "Existing file name has a different size.")
                return {
                    "success": True, "already_present": True, "readback_verified": True,
                    "target_type": target_type, "target_id": target_id,
                    "note_id": note_id, "attachment_id": attachment.get("id"),
                    "file_name": file_name, "content_length": expected_size_bytes,
                    "sha256_status": "not available from attachment metadata",
                }

        # One trusted HTTPS fetch. Reject redirect, HTML, oversize and wrong SHA.
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
        auth = await client._ensure_access_token()
        if not auth.success:
            return _error("AUTH_MISSING", "TrainingPeaks authentication missing.")
        payload = {
            "planId" if target_type == "plan" else "athleteId": target_id,
            "noteId": note_id, "fileName": file_name,
            "contentType": "application/pdf",
            "data": base64.b64encode(blob).decode("ascii"),
        }
        status = None
        try:
            # Direct one-shot POST: no automatic retry after uncertain writes.
            result = await client._client.request(
                "POST", f"{client.base_url}{attachment_url}",
                headers=client._get_headers(), json=payload, timeout=60,
            )
            status = result.status_code
        except Exception:
            pass

        # Reconcile even after timeout: never repeat POST based on an exception.
        after = await all_notes()
        if after is None:
            return _error("WRITE_UNVERIFIED", "Attachment outcome uncertain; inspect provider before retry.")
        final_list = [n for n in after if _note_id(n) == note_id]
        if len(final_list) != 1 or len(after) != len(before) or {
            _note_id(n) for n in after
        } != {_note_id(n) for n in before}:
            return _error("WRITE_UNVERIFIED", "Native notes inventory changed; inspect provider.")
        final = final_list[0]
        baseline_other = {_note_id(n): n for n in before if _note_id(n) != note_id}
        if any(n != baseline_other.get(_note_id(n)) for n in after if _note_id(n) != note_id):
            return _error("WRITE_UNVERIFIED", "Unexpected change in another note.")
        if {k: v for k, v in final.items() if k != "attachments"} != {
            k: v for k, v in target.items() if k != "attachments"
        }:
            return _error("WRITE_UNVERIFIED", "Note content changed unexpectedly.")
        current = final.get("attachments") or []
        match = [
            a for a in current if a.get("fileName") == file_name
            and int(a.get("contentLength") or -1) == expected_size_bytes
            and a.get("id") is not None
        ]
        if len(match) != 1 or len(current) != len(old) + 1:
            return _error("WRITE_UNVERIFIED" if status in (None, 200, 201, 204)
                          else "PROVIDER_REJECTED",
                          "Native PDF attachment not verified; inspect before retry.")
        if target_type == "plan":
            after_plan = await client.get(f"/plans/v1/plans/{target_id}")
            if (after_plan.is_error or not isinstance(after_plan.data, dict)
                or any(after_plan.data.get(k) != plan.get(k)
                       for k in ("planId", "title", "workoutCount", "weekCount", "isPublic", "price"))):
                return _error("WRITE_UNVERIFIED", "Plan metadata changed or could not be verified.")
        else:
            detail = await client.get(f"/fitness/v1/athletes/{target_id}/calendarNote/{note_id}")
            if (detail.is_error or not isinstance(detail.data, dict)
                or _note_id(detail.data) != note_id
                or detail.data.get("title") != target.get("title")
                or detail.data.get("description") != target.get("description")
                or not any(a.get("id") == match[0]["id"]
                           for a in detail.data.get("attachments") or [])):
                return _error("WRITE_UNVERIFIED", "Athlete note detail readback mismatch.")

        return {
            "success": True, "readback_verified": True, "already_present": False,
            "target_type": target_type, "target_id": target_id,
            "note_id": note_id, "attachment_id": match[0]["id"],
            "file_name": file_name, "content_length": expected_size_bytes,
            "sha256": expected_sha256.lower(), "note_count": len(after),
            **({"workout_count": plan.get("workoutCount")} if plan is not None else {}),
        }


async def tp_attach_training_plan_note_pdf(
    plan_id: int, note_id: int, file_name: str, source_url: str,
    expected_sha256: str, expected_size_bytes: int,
) -> dict[str, Any]:
    """Backwards-compatible alias for existing coach-owned Training Plan notes."""
    result = await tp_attach_native_note_pdf(
        target_type="plan", target_id=plan_id, note_id=note_id,
        file_name=file_name, source_url=source_url,
        expected_sha256=expected_sha256,
        expected_size_bytes=expected_size_bytes,
    )
    if result.get("success"):
        result["plan_id"] = plan_id
    return result
