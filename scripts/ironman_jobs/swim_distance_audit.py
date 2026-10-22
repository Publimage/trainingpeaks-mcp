"""Read-only, deterministic audit of planned versus native swim metres.

Small reusable pilot: no TrainingPeaks, Drive, network, credentials, or writes.
Understands native distance steps and timed Recover steps in the structured
Swim representation already used by the existing CHASING generator.
Other structures fail closed instead of being silently accepted.
"""

from __future__ import annotations

import math
from typing import Any


class UnsupportedSwimStructure(ValueError):
    """The workout cannot be checked safely with this pilot's parser."""


def _positive_integer(value: Any, label: str) -> int:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise UnsupportedSwimStructure(f"{label}:NOT_A_FINITE_NUMBER")
    if value <= 0 or not float(value).is_integer():
        raise UnsupportedSwimStructure(f"{label}:NOT_A_POSITIVE_INTEGER")
    return int(value)


def _count_block_metres(block: Any) -> int:
    if not isinstance(block, dict):
        raise UnsupportedSwimStructure("BLOCK_NOT_OBJECT")
    block_type = block.get("type")
    if block_type not in ("step", "repetition"):
        raise UnsupportedSwimStructure("BLOCK_TYPE_UNSUPPORTED")
    length = block.get("length")
    if not isinstance(length, dict) or length.get("unit") != "repetition":
        raise UnsupportedSwimStructure("BLOCK_LENGTH_UNSUPPORTED")
    repetitions = _positive_integer(length.get("value"), "BLOCK_REPETITIONS")
    if block_type == "step" and repetitions != 1:
        raise UnsupportedSwimStructure("STEP_MULTIPLIER_UNEXPECTED")
    steps = block.get("steps")
    if not isinstance(steps, list) or not steps:
        raise UnsupportedSwimStructure("BLOCK_STEPS_MISSING")

    metres_per_repetition = 0
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("length"), dict):
            raise UnsupportedSwimStructure("STEP_LENGTH_MISSING")
        if step.get("openDuration") is True:
            raise UnsupportedSwimStructure("OPEN_DURATION_UNSUPPORTED")
        unit = step["length"].get("unit")
        value = _positive_integer(step["length"].get("value"), "STEP_LENGTH")
        if unit == "meter":
            metres_per_repetition += value
        elif unit == "second":
            if step.get("intensityClass") != "rest":
                raise UnsupportedSwimStructure("TIMED_ACTIVE_STEP_UNSUPPORTED")
            # Rest measured in seconds adds zero metres.
        else:
            raise UnsupportedSwimStructure("STEP_UNIT_UNSUPPORTED")

    return repetitions * metres_per_repetition


def audit_swim_distance(distance_planned: Any, native_structure: Any) -> dict[str, Any]:
    """Return PASS/FAIL and measured delta; never guess missing swim distance.

    Input native_structure is the provider's structure object containing a
    structure array. This checks arithmetic only, not recovery order,
    intensity prescription, workout quality, or other Builder invariants.
    """
    try:
        declared = _positive_integer(distance_planned, "DISTANCE_PLANNED")
        if not isinstance(native_structure, dict):
            raise UnsupportedSwimStructure("STRUCTURE_NOT_OBJECT")
        if native_structure.get("primaryLengthMetric") != "distance":
            raise UnsupportedSwimStructure("PRIMARY_LENGTH_NOT_DISTANCE")
        blocks = native_structure.get("structure")
        if not isinstance(blocks, list) or not blocks:
            raise UnsupportedSwimStructure("BLOCKS_MISSING")
        computed = sum(_count_block_metres(block) for block in blocks)
        if computed <= 0:
            raise UnsupportedSwimStructure("NO_SWIM_METRES")
    except UnsupportedSwimStructure as exc:
        return {"status": "FAIL", "code": "SWIM_DISTANCE_UNVERIFIABLE", "reason": str(exc)}

    delta = computed - declared
    return {
        "status": "PASS" if delta == 0 else "FAIL",
        "code": "SWIM_DISTANCE_OK" if delta == 0 else "SWIM_DISTANCE_MISMATCH",
        "declared_m": declared,
        "computed_m": computed,
        "delta_m": delta,
    }
