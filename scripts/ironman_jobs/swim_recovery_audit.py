"""Pure swim-pause checker: no network, file writes, or provider operations.

Generalizes PR13's ordered native Recover comparison without importing its
product generator or writer. The caller supplies an independent reviewed
prescription. Never infer that prescription from the Builder being checked.
A source_ref is provenance supplied by the caller, NOT proof of approval.
"""
from __future__ import annotations

from collections import Counter
import math
from typing import Any

from scripts.ironman_jobs.swim_distance_audit import audit_swim_distance

SCHEMA = "IRONMAN_SWIM_RECOVERY_V1"
MAX_STEPS = 10000  # Computational bound, not a training recommendation.


class Unverifiable(ValueError):
    """Input does not support a reliable decision."""


def _integer(value: Any, minimum: int, field: str) -> int:
    if type(value) is int:
        number = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        number = int(value)
    else:
        raise Unverifiable(field + ":INVALID_INTEGER")
    if number < minimum:
        raise Unverifiable(field + ":OUT_OF_RANGE")
    return number


def _prescription(spec: Any) -> tuple[int, list[tuple[int, int]]]:
    keys = {"schema", "source_ref", "coverage", "total_m", "pauses"}
    if not isinstance(spec, dict) or set(spec) != keys:
        raise Unverifiable("PRESCRIPTION_FIELDS_REQUIRED")
    if spec["schema"] != SCHEMA:
        raise Unverifiable("PRESCRIPTION_SCHEMA_UNSUPPORTED")
    if not isinstance(spec["source_ref"], str) or not spec["source_ref"].strip():
        raise Unverifiable("INDEPENDENT_SOURCE_REQUIRED")
    if spec["coverage"] not in ("complete", "targeted"):
        raise Unverifiable("COVERAGE_REQUIRED")
    total = _integer(spec["total_m"], 1, "TOTAL_METRES")
    pauses = spec["pauses"]
    if not isinstance(pauses, list) or len(pauses) > MAX_STEPS:
        raise Unverifiable("PAUSES_INVALID_OR_TOO_LARGE")
    if spec["coverage"] == "targeted" and not pauses:
        raise Unverifiable("TARGETED_CHECK_CANNOT_BE_EMPTY")
    expected = []
    previous = 0
    for pause in pauses:
        if not isinstance(pause, dict) or set(pause) != {"after_m", "seconds"}:
            raise Unverifiable("EXPLICIT_PAUSE_POSITION_AND_DURATION_REQUIRED")
        position = _integer(pause["after_m"], 0, "PAUSE_POSITION")
        seconds = _integer(pause["seconds"], 1, "PAUSE_SECONDS")
        if not previous <= position <= total:
            raise Unverifiable("PAUSE_POSITION_OUT_OF_ORDER_OR_RANGE")
        expected.append((position, seconds))
        previous = position
    return total, expected


def _records(events: list[tuple[int, int]]) -> list[dict[str, int]]:
    return [{"after_m": p, "seconds": s} for p, s in events]


def _zero_rest_target(step: dict[str, Any]) -> bool:
    targets = step.get("targets")
    if not isinstance(targets, list) or len(targets) != 1:
        return False
    target = targets[0]
    return isinstance(target, dict) and all(
        type(target.get(k)) in (int, float) and target[k] == 0
        for k in ("minValue", "maxValue")
    )


def audit_swim_recoveries(spec: Any, native_structure: Any) -> dict[str, Any]:
    """Check explicit stationary pauses at cumulative swim distances.

    PASS applies only to complete pause prescriptions, never to full workout
    quality. A successful targeted check returns PARTIAL. Unknown/ambiguous
    input returns UNVERIFIABLE. All three non-PASS states block a full release
    gate. No N versus N-1 recovery convention is imposed by this function.
    Rest-labelled metres count as swimming, not stationary seconds.
    """
    try:
        total, expected = _prescription(spec)
        if not isinstance(native_structure, dict):
            raise Unverifiable("STRUCTURE_REQUIRED")
        blocks = native_structure.get("structure")
        if not isinstance(blocks, list) or len(blocks) > MAX_STEPS:
            raise Unverifiable("BLOCKS_INVALID_OR_TOO_LARGE")
        distance = audit_swim_distance(total, native_structure)
        if distance["code"] == "SWIM_DISTANCE_UNVERIFIABLE":
            raise Unverifiable(distance["reason"])
        if distance["status"] != "PASS":
            return {"status": "FAIL", "code": "SWIM_RECOVERY_DISTANCE_MISMATCH",
                    "distance_check": distance}
        expanded_size = sum(int(b["length"]["value"]) * len(b["steps"]) for b in blocks)
        if expanded_size > MAX_STEPS:
            raise Unverifiable("EXPANDED_STEP_LIMIT")
        actual = []
        metres = 0
        for block in blocks:
            for _ in range(int(block["length"]["value"])):
                for step in block["steps"]:
                    value = int(step["length"]["value"])
                    if step["length"]["unit"] == "meter":
                        metres += value
                    else:  # Distance validator accepts only seconds + rest here.
                        if not _zero_rest_target(step):
                            return {"status": "FAIL", "code": "SWIM_RECOVERY_TARGET_INVALID",
                                    "after_m": metres, "seconds": value}
                        actual.append((metres, value))
    except Unverifiable as exc:
        return {"status": "UNVERIFIABLE", "code": "SWIM_RECOVERY_UNVERIFIABLE",
                "reason": str(exc)}

    if spec["coverage"] == "complete":
        matches = actual == expected
        status = "PASS" if matches else "FAIL"
    else:
        cursor = iter(actual)
        matches = all(any(item == required for item in cursor) for required in expected)
        status = "PARTIAL" if matches else "FAIL"
    missing = list((Counter(expected) - Counter(actual)).elements())
    unexpected = list((Counter(actual) - Counter(expected)).elements())
    return {
        "status": status,
        "code": "SWIM_RECOVERY_MATCH" if matches else "SWIM_RECOVERY_MISMATCH",
        "coverage": spec["coverage"], "source_ref": spec["source_ref"],
        "computed_m": metres,
        "expected_pauses": _records(expected), "actual_pauses": _records(actual),
        "missing_pauses": _records(missing), "additional_pauses": _records(unexpected),
        "expected_rest_seconds": sum(s for _, s in expected),
        "actual_rest_seconds": sum(s for _, s in actual),
        "sequence_matches": matches,
    }
