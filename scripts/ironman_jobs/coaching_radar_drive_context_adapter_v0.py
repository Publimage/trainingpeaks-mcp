"""Read-only Google Drive adapter for future Coaching Radar AI context.

No credential, document ID or Knowledge Base content is committed to the repo.
Runtime access is intended for a dedicated service account shared as Viewer only
with the IRONMAN Knowledge Base folder. Authentication dependency is imported
lazily so isolated CI requires no Google credentials.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from scripts.ironman_jobs.coaching_radar_kb_context_v0 import (
    REQUIRED_ROLES,
    SOURCE_OF_TRUTH,
    validate_kb_context_manifest,
)

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
EXPORT_MIME = "text/markdown"
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class ContextDocumentSpec:
    role: str
    document_id: str
    expected_title: str


class GoogleDriveContextReader:
    def __init__(self, session: Any, *, now_fn=None):
        self._session = session
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def _get(self, url: str):
        response = self._session.get(url, timeout=30)
        if getattr(response, "status_code", None) != 200:
            raise RuntimeError(f"KB_DRIVE_HTTP_{getattr(response, 'status_code', 'UNKNOWN')}")
        return response

    def read_document(self, spec: ContextDocumentSpec) -> tuple[dict[str, Any], str]:
        if not spec.document_id or not spec.expected_title or not spec.role:
            raise ValueError("KB_DOCUMENT_SPEC_INVALID")

        encoded_id = quote(spec.document_id, safe="")
        fields = quote("id,name,mimeType,version,modifiedTime,trashed", safe=",")
        meta_url = f"https://www.googleapis.com/drive/v3/files/{encoded_id}?fields={fields}"
        meta = self._get(meta_url).json()

        if meta.get("id") != spec.document_id:
            raise RuntimeError("KB_DRIVE_DOCUMENT_ID_MISMATCH")
        if meta.get("name") != spec.expected_title:
            raise RuntimeError("KB_DRIVE_DOCUMENT_TITLE_MISMATCH")
        if meta.get("mimeType") != GOOGLE_DOC_MIME:
            raise RuntimeError("KB_DRIVE_DOCUMENT_MIME_MISMATCH")
        if meta.get("trashed") is True:
            raise RuntimeError("KB_DRIVE_DOCUMENT_TRASHED")
        version = str(meta.get("version") or "").strip()
        if not version.isdigit():
            raise RuntimeError("KB_DRIVE_VERSION_MISSING")

        export_url = (
            f"https://www.googleapis.com/drive/v3/files/{encoded_id}/export"
            f"?mimeType={quote(EXPORT_MIME, safe='')}"
        )
        response = self._get(export_url)
        content_bytes = bytes(response.content)
        if not content_bytes:
            raise RuntimeError("KB_DRIVE_DOCUMENT_EMPTY")
        if len(content_bytes) > MAX_DOCUMENT_BYTES:
            raise RuntimeError("KB_DRIVE_DOCUMENT_TOO_LARGE")
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError("KB_DRIVE_DOCUMENT_NOT_UTF8") from exc

        retrieved = self._now_fn().astimezone(timezone.utc).isoformat()
        entry = {
            "title": meta["name"],
            "document_id": meta["id"],
            "source_version": version,
            "version_kind": "DRIVE_FILE_VERSION",
            "modified_time": meta.get("modifiedTime"),
            "retrieved_at_utc": retrieved,
            "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
            "source": "GOOGLE_DRIVE",
        }
        return entry, content


def service_account_session(credentials_file: str):
    """Create an AuthorizedSession with the single Drive read-only scope."""
    if not credentials_file:
        raise ValueError("KB_GOOGLE_CREDENTIALS_FILE_REQUIRED")
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError("KB_GOOGLE_AUTH_DEPENDENCY_MISSING") from exc

    credentials = service_account.Credentials.from_service_account_file(
        credentials_file,
        scopes=[DRIVE_READONLY_SCOPE],
    )
    return AuthorizedSession(credentials)


def build_context_bundle(
    reader: GoogleDriveContextReader,
    *,
    athlete_id: int,
    documents: dict[str, ContextDocumentSpec],
    specialist_documents: list[ContextDocumentSpec],
    now_utc: datetime | None = None,
    max_age_hours: float = 24.0,
) -> dict[str, Any]:
    """Read current canonical docs, validate manifest, and return a private in-memory bundle."""
    missing = [role for role in REQUIRED_ROLES if role not in documents]
    if missing:
        raise ValueError("KB_CONTEXT_SPEC_ROLE_MISSING:" + ",".join(missing))
    if not specialist_documents:
        raise ValueError("KB_CONTEXT_SPECIALIST_SPEC_MISSING")

    entries: dict[str, dict[str, Any]] = {}
    contents: dict[str, str] = {}
    for role in REQUIRED_ROLES:
        spec = documents[role]
        if spec.role != role:
            raise ValueError(f"KB_CONTEXT_SPEC_ROLE_MISMATCH:{role}")
        entry, content = reader.read_document(spec)
        entries[role] = entry
        contents[role] = content

    specialist_entries: list[dict[str, Any]] = []
    for index, spec in enumerate(specialist_documents):
        entry, content = reader.read_document(spec)
        specialist_entries.append(entry)
        contents[f"specialist:{index}"] = content

    card_text = contents["athlete_card"]
    binding = re.compile(rf"TrainingPeaks\\s+ID\\s*:\\s*{int(athlete_id)}\\b", re.IGNORECASE)
    if not binding.search(card_text):
        raise ValueError("KB_ATHLETE_CARD_PROVIDER_ID_MISMATCH")

    generated_at = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    manifest = {
        "schema": "IRONMAN_KB_CONTEXT_MANIFEST_V1",
        "source_of_truth": SOURCE_OF_TRUTH,
        "athlete_id": int(athlete_id),
        "generated_at_utc": generated_at.isoformat(),
        "documents": entries,
        "specialist_documents": specialist_entries,
    }
    validation = validate_kb_context_manifest(
        manifest,
        athlete_id=athlete_id,
        now_utc=generated_at,
        max_age_hours=max_age_hours,
    )
    return {
        "manifest": manifest,
        "validation": validation,
        "contents": contents,
    }
