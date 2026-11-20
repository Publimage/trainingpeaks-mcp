"""Compare swim source/destination snapshots without calling TrainingPeaks.

Input JSON files are exports of the TP MCP read-only library/plan readers.
Exit code 0 means the complete comparison passed; 1 means mismatch/incomplete.
No credentials, network calls, or modifications to TrainingPeaks.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def native_blocks(workout: dict[str, Any]) -> dict[str, Any] | None:
    structure = workout.get("structure")
    if isinstance(structure, dict) and isinstance(structure.get("structure"), list):
        return structure
    return None


def normalized_step(step: dict[str, Any]) -> dict[str, Any]:
    length = step.get("length") or {}
    return {
        "name": step.get("name"),
        "length": {"value": length.get("value"), "unit": length.get("unit")},
        "targets": step.get("targets") or [],
        "intensityClass": step.get("intensityClass"),
        "openDuration": bool(step.get("openDuration")),
        "steps": [normalized_step(child) for child in step.get("steps") or []],
    }


def normalized_structure(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        "primaryLengthMetric": payload.get("primaryLengthMetric"),
        "primaryIntensityMetric": payload.get("primaryIntensityMetric"),
        "structure": [
            {"type": group.get("type"),
             "length": {"unit": (group.get("length") or {}).get("unit"),
                        "value": (group.get("length") or {}).get("value")},
             "steps": [normalized_step(step) for step in group.get("steps") or []]}
            for group in payload.get("structure") or []
        ],
    }


def step_totals(payload: dict[str, Any] | None) -> dict[str, float]:
    """Distance in meters and recovery in seconds; never conflate units."""
    totals = {"meters": 0.0, "recovery_seconds": 0.0}
    if not payload:
        return totals

    def scan(step: dict[str, Any], factor: float, is_rest: bool) -> None:
        nested = step.get("steps") or []
        length = step.get("length") or {}
        if nested:
            amount = length.get("value", 1)
            scan_multiplier = factor * float(amount) if length.get("unit") == "repetition" else factor
            for child in nested:
                scan(child, scan_multiplier, is_rest)
            return
        amount = length.get("value")
        if not isinstance(amount, (int, float)):
            return
        if length.get("unit") == "meter":
            totals["meters"] += factor * amount
        if length.get("unit") == "second" and (is_rest or step.get("intensityClass") == "rest"):
            totals["recovery_seconds"] += factor * amount

    for block in payload.get("structure") or []:
        for step in block.get("steps") or []:
            scan(step, float((block.get("length") or {}).get("value") or 1), False)
    return totals


def read_library(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    workout = doc.get("item", doc)
    if not isinstance(workout, dict) or "distancePlanned" not in workout:
        raise ValueError("Library JSON needs an item with distancePlanned")
    return workout


def read_plan(path: Path, workout_id: int) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    workouts = doc.get("workouts", [doc])
    hits = [w for w in workouts if w.get("workout_id") == workout_id]
    if len(hits) != 1:
        raise ValueError(f"Expected one plan workout id {workout_id}, found {len(hits)}")
    return hits[0]


def check(source: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    src = native_blocks(source)
    dst = target.get("native_structure")
    src_m = source.get("distancePlanned")
    dst_m = target.get("native_distance_planned_m")
    src_h = source.get("totalTimePlanned")
    dst_h = target.get("native_duration_planned_h")
    checks = {
        "has_source_structure": src is not None,
        "has_destination_structure": isinstance(dst, dict),
        "planned_distance_equal": isinstance(src_m, (float, int))
        and isinstance(dst_m, (float, int)) and math.isclose(src_m, dst_m, abs_tol=0.01),
        "planned_duration_equal": isinstance(src_h, (float, int))
        and isinstance(dst_h, (float, int)) and math.isclose(src_h, dst_h, abs_tol=1e-6),
        "all_blocks_identical": src is not None and isinstance(dst, dict)
        and normalized_structure(src) == normalized_structure(dst),
        "source_blocks_total_expected_meters": src is not None
        and isinstance(src_m, (int, float))
        and math.isclose(step_totals(src)["meters"], src_m, abs_tol=0.01),
        "destination_blocks_total_expected_meters": isinstance(dst, dict)
        and isinstance(dst_m, (int, float))
        and math.isclose(step_totals(dst)["meters"], dst_m, abs_tol=0.01),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "source_m": src_m, "destination_m": dst_m,
        "source_min": round(src_h * 60, 3) if isinstance(src_h, (int, float)) else None,
        "destination_min": round(dst_h * 60, 3) if isinstance(dst_h, (int, float)) else None,
        "source_recovery_seconds": step_totals(src)["recovery_seconds"],
        "destination_recovery_seconds": step_totals(dst)["recovery_seconds"]
        if isinstance(dst, dict) else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True, help="Read-only library-item JSON")
    parser.add_argument("--plan", type=Path, required=True, help="Read-only plan-workouts JSON")
    parser.add_argument("--workout-id", type=int, required=True, help="Specific destination workout ID")
    args = parser.parse_args()
    try:
        report = check(read_library(args.library), read_plan(args.plan, args.workout_id))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {"status": "FAIL", "error": str(exc)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
