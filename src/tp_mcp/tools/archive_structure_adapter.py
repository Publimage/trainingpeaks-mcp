"""Pure, offline converter: canonical workout JSON -> TrainingPeaks library structure.

This module performs ZERO provider reads/writes, network requests or imports
from client/auth modules. The TP library create tool already backfills polyline.

Keep the archive's canonical human descriptions and fueling content separately.
This converter only maps already APPROVED/PASS interval prescription structures.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_PRIMARY_UNIT = {"duration": "second", "distance": "meter"}
_ALLOWED_UNITS = {"second", "meter"}
_ALLOWED_INTENSITIES = {
    "rpe", "percentOfFtp", "percentOfThresholdPace", "pace", "speed",
    "heartRate", "percentOfHeartRate", "percentOfThresholdHr",
}


class ArchiveStructureError(ValueError):
    """Fail closed: canonical data requires QA before exporting."""


def convert_archive_structure(
    canonical: Mapping[str, Any],
    *,
    expected_primary_total: float | None = None,
    allow_mixed_length_units: bool = False,
) -> dict[str, Any]:
    """Convert an archive 'steps' recipe to TrainingPeaks Workout Library JSON.

    By default blocks containing lengths measured in multiple units (e.g.
    4x500m with 25s recovery) require a separate provider/UI rendering test
    before auto-publish. Sum and QA only the PRIMARY length unit.
    """
    if not isinstance(canonical, Mapping):
        raise ArchiveStructureError("Structure must be an object.")
    length_type = canonical.get("primaryLengthMetric")
    unit = _PRIMARY_UNIT.get(length_type)
    metric = canonical.get("primaryIntensityMetric")
    if not unit or not isinstance(metric, str) or not metric.strip():
        raise ArchiveStructureError("Missing primary length or intensity metric.")
    steps = canonical.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ArchiveStructureError("At least one archive interval is required.")

    def inner_step(s: Mapping[str, Any]) -> dict[str, Any]:
        length = s.get("length")
        if not isinstance(length, dict) or length.get("unit") not in _ALLOWED_UNITS:
            raise ArchiveStructureError("Unsupported step length/unit.")
        n = length.get("value")
        if isinstance(n, bool) or not isinstance(n, (int, float)) or n <= 0:
            raise ArchiveStructureError("Step length must be positive.")
        a, b = s.get("intensityMin"), s.get("intensityMax")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (a, b)) or a > b:
            raise ArchiveStructureError("Intensity range invalid.")
        name = s.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ArchiveStructureError("Step requires a name.")
        kind = s.get("intensityClass")
        if not isinstance(kind, str) or not kind:
            raise ArchiveStructureError("Step requires intensityClass.")
        return {
            "name": name, "length": dict(length),
            "targets": [{"minValue": a, "maxValue": b}],
            "intensityClass": kind, "openDuration": False,
        }

    out = []
    total = 0.0
    mixed = False
    for step in steps:
        if not isinstance(step, dict):
            raise ArchiveStructureError("Each block must be an object.")
        kind = step.get("type")
        if kind == "step":
            reps, exercise_steps = 1, [inner_step(step)]
        elif kind == "repetition":
            reps = step.get("reps")
            if isinstance(reps, bool) or not isinstance(reps, int) or reps < 1:
                raise ArchiveStructureError("Invalid repetition count.")
            contents = step.get("steps")
            if not isinstance(contents, list) or not contents:
                raise ArchiveStructureError("Repetition must contain steps.")
            exercise_steps = [inner_step(s) for s in contents]
        else:
            raise ArchiveStructureError("Unsupported block type.")
        for item in exercise_steps:
            length = item["length"]
            if length["unit"] != unit:
                mixed = True
            else:
                total += reps * float(length["value"])
        out.append({
            "type": "step" if kind == "step" else "repetition",
            "length": {"value": reps, "unit": "repetition"},
            "steps": exercise_steps,
        })
    if mixed and not allow_mixed_length_units:
        raise ArchiveStructureError(
            "Mixed meter/second length units need separate library render QA."
        )
    if expected_primary_total is not None:
        if abs(total - expected_primary_total) > 0.0001:
            raise ArchiveStructureError(
                f"Primary prescription {total:g} != expected {expected_primary_total:g}."
            )
    converted = {
        "primaryLengthMetric": length_type,
        "primaryIntensityMetric": metric,
        "structure": out,
    }
    if length_type == "distance" and canonical.get("visualizationDistanceUnit"):
        converted["visualizationDistanceUnit"] = canonical["visualizationDistanceUnit"]
    return converted
