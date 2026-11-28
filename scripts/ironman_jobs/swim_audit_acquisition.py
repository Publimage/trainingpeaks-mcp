"""Read-only source acquisition for the existing swim validators.

Uses the existing GoogleDriveContextReader.read_document interface and an
already authenticated TPClient. No credentials, identifiers, prose inference,
provider writes, deployment or scheduler configuration live in this module.
Only coach-owned library templates are supported by this first adapter.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from scripts.ironman_jobs.swim_audit_report import (
    SNAPSHOT_SCHEMA, PRESCRIPTION_SCHEMA, audit_swim_report, payload_sha256,
)

RECORD_SCHEMA = "IRONMAN_SWIM_SOURCE_RECORD_V1"
MAX_BYTES = 2 * 1024 * 1024


class AcquisitionStop(ValueError):
    """Known acquisition failure; code contains no source content or secrets."""


@dataclass(frozen=True)
class DocumentSpec:
    # Same public interface as the existing Radar ContextDocumentSpec.
    role: str
    document_id: str
    expected_title: str


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise AcquisitionStop(code)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        _need(key not in obj, "SOURCE_JSON_DUPLICATE_KEY")
        obj[key] = value
    return obj


def _invalid_constant(value: str) -> None:
    raise AcquisitionStop("SOURCE_JSON_NONFINITE")


def extract_record(text: str, section: str) -> dict[str, Any]:
    """Read one explicitly marked JSON record; never interpret free prose."""
    _need(type(text) is str and len(text.encode("utf-8")) <= MAX_BYTES,
          "SOURCE_CONTENT_INVALID")
    _need(type(section) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", section) is not None,
          "SOURCE_SECTION_INVALID")
    begin, end = f"[SWIM_AUDIT_BEGIN:{section}]", f"[SWIM_AUDIT_END:{section}]"
    _need(text.count(begin) == text.count(end) == 1, "SOURCE_SECTION_NOT_UNIQUE")
    start, stop = text.index(begin) + len(begin), text.index(end)
    _need(start < stop, "SOURCE_SECTION_ORDER")
    try:
        obj = json.loads(text[start:stop].strip(), object_pairs_hook=_unique_object,
                         parse_constant=_invalid_constant)
    except (json.JSONDecodeError, RecursionError):
        raise AcquisitionStop("SOURCE_JSON_INVALID") from None
    _need(type(obj) is dict and set(obj) == {"schema", "target", "recovery"},
          "SOURCE_RECORD_FIELDS")
    _need(obj["schema"] == RECORD_SCHEMA, "SOURCE_RECORD_SCHEMA")
    return obj


async def _read(operation: Callable, *args: Any, threaded: bool = False) -> Any:
    # Retry only typed transport failures. Auth/permission/schema failures do
    # not qualify. Upper bound is three attempts, never a changed endpoint.
    for attempt in range(3):
        try:
            if threaded:
                return await asyncio.to_thread(operation, *args)
            return await operation(*args)
        except (TimeoutError, ConnectionError):
            if attempt == 2:
                raise AcquisitionStop("READ_TRANSPORT_UNAVAILABLE") from None
            await asyncio.sleep(0.05 * (2 ** attempt))
        except PermissionError:
            raise AcquisitionStop("READ_PERMISSION_DENIED") from None
        except RuntimeError:
            # Existing Drive reader uses RuntimeError for HTTP/schema failures.
            # Do not echo its text or retry a possible authorization denial.
            raise AcquisitionStop("READER_REJECTED_OR_UNAVAILABLE") from None


def _validate_request(request: Any) -> tuple[dict[str, str], DocumentSpec]:
    keys = {"target", "document_id", "document_title", "section",
            "reviewed_record_sha256", "validator_revision"}
    _need(type(request) is dict and set(request) == keys, "REQUEST_FIELDS")
    target = request["target"]
    _need(type(target) is dict and set(target) ==
          {"provider", "owner_id", "resource_kind", "container_id", "workout_id"},
          "TARGET_FIELDS")
    _need(target["provider"] == "trainingpeaks" and
          target["resource_kind"] == "library_template", "TARGET_SCOPE_UNSUPPORTED")
    for key in ("owner_id", "container_id", "workout_id"):
        _need(type(target[key]) is str and re.fullmatch(r"[1-9][0-9]{0,19}", target[key]) is not None,
              "TARGET_IDENTIFIER_INVALID")
    for key in ("document_id", "document_title", "section"):
        _need(type(request[key]) is str and bool(request[key]) and
              request[key].strip() == request[key], "SOURCE_SELECTOR_INVALID")
    _need(re.fullmatch(r"[A-Za-z0-9_-]{1,80}", request["section"]) is not None,
          "SOURCE_SECTION_INVALID")
    for field, length in (("reviewed_record_sha256", 64), ("validator_revision", 40)):
        value = request[field]
        _need(type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value) is not None,
              "REVIEWED_REFERENCE_INVALID")
    return copy.deepcopy(target), DocumentSpec("swim_audit_prescription",
                                               request["document_id"], request["document_title"])


async def _source(reader: Any, spec: DocumentSpec, now_fn: Callable) -> tuple[dict, str]:
    result = await _read(reader.read_document, spec, threaded=True)
    _need(type(result) in (tuple, list) and len(result) == 2, "SOURCE_READER_RESULT")
    entry, text = result
    _need(type(entry) is dict and type(text) is str and bool(text), "SOURCE_READER_FIELDS")
    raw = text.encode("utf-8")
    _need(len(raw) <= MAX_BYTES, "SOURCE_TOO_LARGE")
    _need(entry.get("source") == "GOOGLE_DRIVE" and
          entry.get("version_kind") == "DRIVE_FILE_VERSION", "SOURCE_PROVIDER_OR_VERSION_KIND")
    _need(entry.get("document_id") == spec.document_id and
          entry.get("title") == spec.expected_title, "SOURCE_IDENTITY_MISMATCH")
    _need(type(entry.get("source_version")) is str and
          re.fullmatch(r"[0-9]+", entry["source_version"]) is not None, "SOURCE_VERSION_MISSING")
    _need(entry.get("content_sha256") == hashlib.sha256(raw).hexdigest(), "SOURCE_CONTENT_HASH_MISMATCH")
    try:
        retrieved = datetime.fromisoformat(entry["retrieved_at_utc"])
        now = now_fn()
        _need(retrieved.utcoffset() is not None and now.utcoffset() is not None,
              "SOURCE_TIMESTAMP_TIMEZONE")
        age = (now - retrieved).total_seconds()
    except (KeyError, TypeError, ValueError):
        raise AcquisitionStop("SOURCE_TIMESTAMP_INVALID") from None
    _need(0 <= age <= 300, "SOURCE_READ_NOT_FRESH")
    return copy.deepcopy(entry), text


async def _get_rows(client: Any, endpoint: str) -> list[dict]:
    response = await _read(client.get, endpoint)
    _need(getattr(response, "is_error", None) is False, "TP_READ_FAILED")
    rows = getattr(response, "data", None)
    _need(type(rows) is list and all(type(row) is dict for row in rows), "TP_ROWS_INVALID")
    return rows


async def read_library_template(client: Any, target: dict[str, str]) -> dict[str, Any]:
    """Uses only the two GET routes already used by the library connector."""
    library_id, item_id = int(target["container_id"]), int(target["workout_id"])
    libraries = await _get_rows(client, "/exerciselibrary/v2/libraries")
    matches = [row for row in libraries if row.get("exerciseLibraryId") == library_id]
    _need(len(matches) == 1, "TP_LIBRARY_NOT_UNIQUE")
    _need(type(matches[0].get("ownerId")) is int and
          matches[0]["ownerId"] == int(target["owner_id"]), "TP_OWNER_MISMATCH")
    rows = await _get_rows(client, f"/exerciselibrary/v2/libraries/{library_id}/items")
    matches = [row for row in rows if row.get("exerciseLibraryItemId") == item_id]
    _need(len(matches) == 1, "TP_ITEM_NOT_UNIQUE")
    item = matches[0]
    _need(type(item.get("exerciseLibraryId")) is int and item["exerciseLibraryId"] == library_id,
          "TP_CONTAINER_MISMATCH")
    _need(item.get("exerciseLibraryItemType") == "WorkoutTemplate" and
          type(item.get("workoutTypeId")) is int and item["workoutTypeId"] == 1,
          "TP_NOT_SWIM_TEMPLATE")
    _need("distancePlanned" in item and "structure" in item, "TP_NATIVE_FIELDS_MISSING")
    return copy.deepcopy(item)


async def acquire_swim_audit(request: Any, *, drive_reader: Any, tp_client: Any,
                             now_fn: Callable | None = None) -> dict[str, Any]:
    """Acquire source and template twice, then run the existing combined report.

    Readers are trusted runtime dependencies, not caller-supplied JSON attestations.
    Their authentication and running revision still need deployment verification.
    Rechecks detect observed drift, not a cross-system transaction or future lock.
    The independently reviewed record digest must not be copied from fetched data.
    """
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    base = {"schema": "IRONMAN_SWIM_ACQUISITION_V1", "publishing_authorized": False,
            "external_authenticity_verified": False, "technical_checks_passed": False,
            "provider_writes": 0, "status": "UNVERIFIABLE"}
    try:
        request = copy.deepcopy(request)
        target, spec = _validate_request(request)
        first, text = await _source(drive_reader, spec, now_fn)
        record = extract_record(text, request["section"])
        _need(record["target"] == target, "SOURCE_TARGET_MISMATCH")
        _need(payload_sha256(record) == request["reviewed_record_sha256"], "SOURCE_RECORD_NOT_REVIEWED")
        _need(type(record["recovery"]) is dict and
              record["recovery"].get("source_ref") == spec.document_id, "SOURCE_RECOVERY_REFERENCE")
        item = await read_library_template(tp_client, target)
        item_digest = payload_sha256(item)
        again = await read_library_template(tp_client, target)
        last, _ = await _source(drive_reader, spec, now_fn)
        _need(payload_sha256(again) == item_digest, "TP_CHANGED_DURING_READ")
        _need(first["source_version"] == last["source_version"] and
              first["content_sha256"] == last["content_sha256"], "SOURCE_CHANGED_DURING_READ")
        snapshot = {"schema": SNAPSHOT_SCHEMA, "target": target,
                    "distance_planned": item["distancePlanned"], "structure": item["structure"]}
        source = {"source_id": spec.document_id,
                  "revision": "DRIVE_FILE_VERSION:" + first["source_version"],
                  "section": request["section"]}
        envelope = {"schema": PRESCRIPTION_SCHEMA, "target": target, "source": source,
                    "snapshot_sha256": payload_sha256(snapshot), "recovery": record["recovery"]}
        report = audit_swim_report(snapshot, envelope, expected_target=target,
                                   expected_source=source, expected_prescription_sha256=payload_sha256(envelope),
                                   validator_revision=request["validator_revision"])
        return {**base, "status": report["status"],
                "technical_checks_passed": report["technical_checks_passed"],
                "code": "SWIM_ACQUISITION_COMPLETE", "report": report,
                "acquisition": {"source_rechecked": True, "template_rechecked": True,
                                "source_version": first["source_version"],
                                "source_content_sha256": first["content_sha256"],
                                "record_sha256": request["reviewed_record_sha256"],
                                "raw_template_sha256": item_digest,
                                "source_read_at_utc": [first["retrieved_at_utc"], last["retrieved_at_utc"]]}}
    except AcquisitionStop as exc:
        return {**base, "code": str(exc)}
    except (TypeError, KeyError, ValueError, OverflowError, RecursionError):
        return {**base, "code": "ACQUISITION_INPUT_UNVERIFIABLE"}
