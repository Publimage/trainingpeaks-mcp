"""Combine existing swim checks with explicit identity/version bindings.

Pure offline function. Expected references must come from an independently
reviewed job manifest, NOT be copied from the packet under test. Matching hashes
prove consistency, not source authenticity, freshness, approval or permission.
No provider, filesystem, environment, clock, scheduling or publishing access.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from scripts.ironman_jobs.swim_distance_audit import audit_swim_distance
from scripts.ironman_jobs.swim_recovery_audit import audit_swim_recoveries

SNAPSHOT_SCHEMA = "IRONMAN_SWIM_SNAPSHOT_V1"
PRESCRIPTION_SCHEMA = "IRONMAN_SWIM_PRESCRIPTION_ENVELOPE_V1"
REPORT_SCHEMA = "IRONMAN_SWIM_AUDIT_REPORT_V1"
TARGET_KEYS = {"provider", "owner_id", "resource_kind", "container_id", "workout_id"}
SOURCE_KEYS = {"source_id", "revision", "section"}


class BindingError(ValueError):
    """Inputs cannot safely be associated with the requested job."""


def payload_sha256(value: Any) -> str:
    """Hash a JSON value without rounding numbers or accepting NaN/Infinity."""
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise BindingError(code)


def _text_record(value: Any, keys: set[str], label: str) -> None:
    _require(type(value) is dict and set(value) == keys, label + "_FIELDS")
    _require(all(type(v) is str and v.strip() == v and bool(v) for v in value.values()),
             label + "_VALUES")


def _target(value: Any) -> None:
    _text_record(value, TARGET_KEYS, "TARGET")
    _require(value["provider"] == "trainingpeaks", "PROVIDER_UNSUPPORTED")
    _require(value["resource_kind"] in ("library_template", "training_plan_workout"),
             "RESOURCE_KIND_UNSUPPORTED")


def _sha(value: Any, length: int) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value) is not None


def _run_check(function: Any, *args: Any) -> dict[str, Any]:
    # Malformed data in a child checker must not become a successful report.
    # Do not catch resource failures or unrelated runtime/programming exceptions.
    try:
        result = function(*args)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
        return {"status": "UNVERIFIABLE", "code": "CHECK_INPUT_UNVERIFIABLE"}
    if result.get("code") == "SWIM_DISTANCE_UNVERIFIABLE":
        result = dict(result, status="UNVERIFIABLE")
    return result


def audit_swim_report(
    snapshot: Any,
    prescription: Any,
    *,
    expected_target: Any,
    expected_source: Any,
    expected_prescription_sha256: Any,
    validator_revision: Any,
) -> dict[str, Any]:
    """Return one report; PASS is restricted to distance and explicit pauses.

    Snapshot fields: schema, target, distance_planned, structure.
    Prescription fields: schema, target, source, snapshot_sha256, recovery.
    Source fields: source_id, revision, section (all non-empty strings).
    recovery.source_ref must equal source.source_id. The trusted caller is
    responsible for loading the current source, review and ownership checks.
    validator_revision is recorded as a caller-supplied revision, not attested.
    """
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "scope": ["swim_distance", "stationary_recoveries"],
        "status": "UNVERIFIABLE",
        "technical_checks_passed": False,
        "publishing_authorized": False,
        "external_authenticity_verified": False,
        "not_checked": ["source_authenticity_and_freshness", "human_approval",
                        "live_provider_ownership", "running_code_revision",
                        "physiological_quality", "total_duration", "graph", "free_text"],
        "checks": {
            "binding": {"status": "UNVERIFIABLE", "code": "BINDING_NOT_CHECKED"},
            "distance": {"status": "NOT_RUN"},
            "recoveries": {"status": "NOT_RUN"},
        },
    }
    try:
        _target(expected_target)
        _text_record(expected_source, SOURCE_KEYS, "EXPECTED_SOURCE")
        _require(_sha(validator_revision, 40), "VALIDATOR_REVISION_REQUIRED")
        _require(_sha(expected_prescription_sha256, 64), "REVIEWED_DIGEST_REQUIRED")
        _require(type(snapshot) is dict and set(snapshot) ==
                 {"schema", "target", "distance_planned", "structure"}, "SNAPSHOT_FIELDS")
        _require(snapshot["schema"] == SNAPSHOT_SCHEMA, "SNAPSHOT_SCHEMA")
        _target(snapshot["target"])
        _require(snapshot["target"] == expected_target, "SNAPSHOT_TARGET_MISMATCH")
        _require(type(prescription) is dict and set(prescription) ==
                 {"schema", "target", "source", "snapshot_sha256", "recovery"},
                 "PRESCRIPTION_ENVELOPE_FIELDS")
        _require(prescription["schema"] == PRESCRIPTION_SCHEMA, "PRESCRIPTION_ENVELOPE_SCHEMA")
        _target(prescription["target"])
        _require(prescription["target"] == expected_target, "PRESCRIPTION_TARGET_MISMATCH")
        _text_record(prescription["source"], SOURCE_KEYS, "SOURCE")
        _require(prescription["source"] == expected_source, "SOURCE_VERSION_MISMATCH")
        recovery = prescription["recovery"]
        _require(type(recovery) is dict and recovery.get("source_ref") ==
                 expected_source["source_id"], "RECOVERY_SOURCE_MISMATCH")
        snapshot_digest = payload_sha256(snapshot)
        _require(_sha(prescription["snapshot_sha256"], 64) and
                 prescription["snapshot_sha256"] == snapshot_digest, "SNAPSHOT_CHANGED")
        prescription_digest = payload_sha256(prescription)
        _require(prescription_digest == expected_prescription_sha256, "PRESCRIPTION_CHANGED")
    except BindingError as exc:
        report["checks"]["binding"] = {"status": "UNVERIFIABLE", "code": str(exc)}
        return report
    except (TypeError, ValueError, OverflowError, RecursionError):
        report["checks"]["binding"] = {"status": "UNVERIFIABLE", "code": "NON_JSON_INPUT"}
        return report

    report.update({
        "target": copy.deepcopy(expected_target),
        "source": copy.deepcopy(expected_source),
        "snapshot_sha256": snapshot_digest,
        "prescription_sha256": prescription_digest,
        "declared_validator_revision": validator_revision,
    })
    report["checks"]["binding"] = {"status": "PASS", "code": "INPUT_BINDINGS_MATCH"}
    distance = _run_check(audit_swim_distance, snapshot["distance_planned"], snapshot["structure"])
    recoveries = _run_check(audit_swim_recoveries, recovery, snapshot["structure"])
    report["checks"].update(distance=distance, recoveries=recoveries)
    states = {distance.get("status"), recoveries.get("status")}
    # Keep a real failure visible even when a different check is inconclusive.
    if "FAIL" in states:
        status = "FAIL"
    elif not states <= {"PASS", "PARTIAL"}:
        status = "UNVERIFIABLE"
    elif "PARTIAL" in states:
        status = "PARTIAL"
    else:
        status = "PASS"
    report["status"] = status
    report["technical_checks_passed"] = status == "PASS"
    return report
