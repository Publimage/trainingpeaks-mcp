"""Fail-closed contract for canonical Google Drive context used by future Radar AI stages.

This module deliberately does NOT fetch Google Drive and does NOT contain private
document IDs or document contents. It validates a context manifest produced by an
authorized Drive adapter before any AI interpretation is allowed to run.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

SCHEMA = "IRONMAN_KB_CONTEXT_MANIFEST_V1"
SOURCE_OF_TRUTH = "IRONMAN — KNOWLEDGE BASE"
REQUIRED_ROLES = (
    "core_index",
    "master_coaching_context",
    "decision_log",
    "open_questions_roadmap",
    "athlete_card",
    "workstream_state",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("KB_TIMESTAMP_MUST_BE_TZ_AWARE")
    return parsed.astimezone(timezone.utc)


def _validate_document(item: dict[str, Any], *, now: datetime, max_age_hours: float) -> None:
    for field in ("title", "document_id", "revision_id", "retrieved_at_utc", "content_sha256"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise ValueError(f"KB_DOCUMENT_FIELD_MISSING:{field}")
    if item.get("source") != "GOOGLE_DRIVE":
        raise ValueError("KB_DOCUMENT_SOURCE_NOT_GOOGLE_DRIVE")
    if not _HEX64.fullmatch(item["content_sha256"]):
        raise ValueError("KB_DOCUMENT_SHA256_INVALID")

    retrieved = _utc(item["retrieved_at_utc"])
    if retrieved > now:
        raise ValueError("KB_DOCUMENT_TIMESTAMP_IN_FUTURE")
    age_hours = (now - retrieved).total_seconds() / 3600
    if age_hours > max_age_hours:
        raise ValueError("KB_DOCUMENT_STALE")


def validate_kb_context_manifest(
    manifest: dict[str, Any],
    *,
    athlete_id: int,
    now_utc: datetime | None = None,
    max_age_hours: float = 24.0,
) -> dict[str, Any]:
    """Validate provenance/freshness; return compact metadata safe for orchestration logs."""
    if manifest.get("schema") != SCHEMA:
        raise ValueError("KB_MANIFEST_SCHEMA_MISMATCH")
    if manifest.get("source_of_truth") != SOURCE_OF_TRUTH:
        raise ValueError("KB_SOURCE_OF_TRUTH_MISMATCH")
    if int(manifest.get("athlete_id") or 0) != int(athlete_id):
        raise ValueError("KB_MANIFEST_ATHLETE_MISMATCH")
    if max_age_hours <= 0:
        raise ValueError("KB_MAX_AGE_INVALID")

    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generated = _utc(str(manifest.get("generated_at_utc") or ""))
    if generated > now:
        raise ValueError("KB_MANIFEST_TIMESTAMP_IN_FUTURE")
    if (now - generated).total_seconds() / 3600 > max_age_hours:
        raise ValueError("KB_MANIFEST_STALE")

    documents = manifest.get("documents")
    if not isinstance(documents, dict):
        raise ValueError("KB_DOCUMENTS_MISSING")

    missing = [role for role in REQUIRED_ROLES if not isinstance(documents.get(role), dict)]
    if missing:
        raise ValueError("KB_CRITICAL_ROLE_MISSING:" + ",".join(missing))

    specialist = manifest.get("specialist_documents")
    if not isinstance(specialist, list) or not specialist:
        raise ValueError("KB_SPECIALIST_DOCUMENT_MISSING")

    all_items: list[tuple[str, dict[str, Any]]] = []
    for role in REQUIRED_ROLES:
        item = documents[role]
        _validate_document(item, now=now, max_age_hours=max_age_hours)
        all_items.append((role, item))
    for index, item in enumerate(specialist):
        if not isinstance(item, dict):
            raise ValueError("KB_SPECIALIST_DOCUMENT_INVALID")
        _validate_document(item, now=now, max_age_hours=max_age_hours)
        all_items.append((f"specialist:{index}", item))

    ids = [item["document_id"] for _, item in all_items]
    if len(ids) != len(set(ids)):
        raise ValueError("KB_DUPLICATE_DOCUMENT_ID")

    revisions = {
        role: {
            "document_id": item["document_id"],
            "revision_id": item["revision_id"],
            "content_sha256": item["content_sha256"],
        }
        for role, item in all_items
    }
    fingerprint = hashlib.sha256(
        json.dumps(revisions, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "schema": SCHEMA,
        "athlete_id": int(athlete_id),
        "generated_at_utc": manifest["generated_at_utc"],
        "document_count": len(all_items),
        "fixed_role_count": len(REQUIRED_ROLES),
        "specialist_document_count": len(specialist),
        "context_fingerprint_sha256": fingerprint,
        "freshness_max_age_hours": max_age_hours,
        "ai_context_gate": "PASS",
    }
