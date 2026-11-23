"""Workout structure builder, validator, and IF/TSS computation.

Converts a simplified step-based structure format into the wire format
expected by the TrainingPeaks API, including cumulative begin/end times
and polyline generation.
"""

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from tp_mcp.tools._validation import format_validation_error
from tp_mcp.tools.library import build_native_repeat_structure

logger = logging.getLogger("tp-mcp")

# Valid intensity classes for workout steps
INTENSITY_CLASSES = {"warmUp", "active", "rest", "coolDown", "other"}

# Valid primary intensity metrics
INTENSITY_METRICS = {"percentOfFtp", "percentOfThresholdHr", "percentOfThresholdPace"}


class SimpleStep(BaseModel):
    """A single workout step in the simplified input format."""

    name: str = Field(min_length=1, max_length=100)
    type: str = Field(default="step")
    duration_seconds: int = Field(gt=0, le=86400)
    intensity_min: float = Field(ge=0, le=300)
    intensity_max: float = Field(ge=0, le=300)
    intensityClass: str = Field(default="active")  # noqa: N815
    cadence_min: float | None = Field(default=None, ge=0, le=300)
    cadence_max: float | None = Field(default=None, ge=0, le=300)

    @field_validator("intensityClass")
    @classmethod
    def check_intensity_class(cls, v: str) -> str:
        if v not in INTENSITY_CLASSES:
            valid = ", ".join(sorted(INTENSITY_CLASSES))
            raise ValueError(f"Invalid intensityClass '{v}'. Valid: {valid}")
        return v

    @model_validator(mode="after")
    def check_intensity_range(self) -> "SimpleStep":
        if self.intensity_min > self.intensity_max:
            raise ValueError("intensity_min must be <= intensity_max")
        if (
            self.cadence_min is not None
            and self.cadence_max is not None
            and self.cadence_min > self.cadence_max
        ):
            raise ValueError("cadence_min must be <= cadence_max")
        return self


class SimpleRepetitionBlock(BaseModel):
    """A repetition block containing multiple steps repeated N times."""

    type: str = Field(default="repetition")
    name: str = Field(default="Repeat")
    reps: int = Field(gt=0, le=100)
    steps: list[SimpleStep] = Field(min_length=1)


class SimpleWorkoutStructure(BaseModel):
    """Top-level simplified structure input from the LLM."""

    primaryIntensityMetric: str = Field(default="percentOfFtp")  # noqa: N815
    steps: list[SimpleStep | SimpleRepetitionBlock] = Field(min_length=1)

    @field_validator("primaryIntensityMetric")
    @classmethod
    def check_metric(cls, v: str) -> str:
        if v not in INTENSITY_METRICS:
            valid = ", ".join(sorted(INTENSITY_METRICS))
            raise ValueError(f"Invalid primaryIntensityMetric '{v}'. Valid: {valid}")
        return v


def _build_step_wire(step: SimpleStep) -> dict[str, Any]:
    """Convert a SimpleStep to wire format."""
    targets: list[dict[str, Any]] = [
        {"minValue": step.intensity_min, "maxValue": step.intensity_max},
    ]
    if step.cadence_min is not None and step.cadence_max is not None:
        targets.append(
            {
                "minValue": step.cadence_min,
                "maxValue": step.cadence_max,
                "unit": "roundOrStridePerMinute",
            }
        )

    return {
        "name": step.name,
        "type": "step",
        "length": {"value": step.duration_seconds, "unit": "second"},
        "targets": targets,
        "intensityClass": step.intensityClass,
        "openDuration": False,
    }


def _compute_block_duration(block: SimpleStep | SimpleRepetitionBlock) -> int:
    """Compute total duration of a block in seconds."""
    if isinstance(block, SimpleRepetitionBlock):
        inner_duration = sum(s.duration_seconds for s in block.steps)
        return inner_duration * block.reps
    return block.duration_seconds


def build_wire_structure(structure: SimpleWorkoutStructure) -> dict[str, Any]:
    """Convert simplified workout steps using the single shared native Builder.

    Normalized groups are compiled by the same engine used for Training Plans,
    Workout Library templates, and athlete-calendar workouts. Repeated blocks
    retain every prescribed recovery, including recovery after the last rep.
    """
    groups: list[dict[str, Any]] = []
    for block in structure.steps:
        if isinstance(block, SimpleRepetitionBlock):
            groups.append({
                "count": block.reps,
                "steps": [_build_step_wire(step) for step in block.steps],
            })
        else:
            groups.append({
                "count": 1,
                "steps": [_build_step_wire(block)],
            })
    return build_native_repeat_structure(
        groups, length_metric="duration",
        intensity_metric=structure.primaryIntensityMetric,
    )


def compute_if_tss(structure: SimpleWorkoutStructure) -> tuple[float, float, int]:
    """Compute IF and TSS from a workout structure.

    Uses NP-style time-weighted 4th-power average of midpoint intensities.
    IF = (weighted_sum / total_seconds) ^ 0.25 / 100
    TSS = (total_seconds * IF^2 * 100) / 3600

    Args:
        structure: The simplified workout structure.

    Returns:
        Tuple of (IF, TSS, total_duration_seconds).
    """
    weighted_sum = 0.0
    total_seconds = 0

    for block in structure.steps:
        if isinstance(block, SimpleRepetitionBlock):
            for _rep in range(block.reps):
                for step in block.steps:
                    midpoint = (step.intensity_min + step.intensity_max) / 2.0
                    weighted_sum += step.duration_seconds * (midpoint ** 4)
                    total_seconds += step.duration_seconds
        else:
            midpoint = (block.intensity_min + block.intensity_max) / 2.0
            weighted_sum += block.duration_seconds * (midpoint ** 4)
            total_seconds += block.duration_seconds

    if total_seconds == 0:
        return 0.0, 0.0, 0

    intensity_factor = (weighted_sum / total_seconds) ** 0.25 / 100.0
    tss = (total_seconds * intensity_factor ** 2 * 100.0) / 3600.0

    return round(intensity_factor, 3), round(tss, 1), total_seconds


def parse_structure_input(structure_input: dict[str, Any] | str) -> SimpleWorkoutStructure:
    """Parse structure input from either a dict or JSON string.

    Args:
        structure_input: Structure as dict or JSON string.

    Returns:
        Parsed SimpleWorkoutStructure.

    Raises:
        ValidationError: If structure is invalid.
        ValueError: If JSON is malformed.
    """
    if isinstance(structure_input, str):
        try:
            data = json.loads(structure_input)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in structure: {e}") from e
    else:
        data = structure_input

    # Parse steps - distinguish between simple steps and repetition blocks
    raw_steps = data.get("steps", [])
    parsed_steps: list[SimpleStep | SimpleRepetitionBlock] = []

    for raw_step in raw_steps:
        if raw_step.get("type") == "repetition":
            parsed_steps.append(SimpleRepetitionBlock.model_validate(raw_step))
        else:
            parsed_steps.append(SimpleStep.model_validate(raw_step))

    return SimpleWorkoutStructure(
        primaryIntensityMetric=data.get("primaryIntensityMetric", "percentOfFtp"),
        steps=parsed_steps,
    )


async def tp_validate_structure(structure: str) -> dict[str, Any]:
    """Validate a workout interval structure without creating a workout.

    Args:
        structure: JSON string of the simplified structure format.

    Returns:
        Dict with validation result (block count, total duration, metric) or error.
    """
    try:
        parsed = parse_structure_input(structure)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }

    intensity_factor, tss, total_seconds = compute_if_tss(parsed)

    # Count blocks
    block_count = len(parsed.steps)
    step_count = 0
    for block in parsed.steps:
        if isinstance(block, SimpleRepetitionBlock):
            step_count += len(block.steps) * block.reps
        else:
            step_count += 1

    return {
        "valid": True,
        "block_count": block_count,
        "total_steps": step_count,
        "total_duration_seconds": total_seconds,
        "total_duration_minutes": round(total_seconds / 60, 1),
        "estimated_if": intensity_factor,
        "estimated_tss": tss,
        "intensity_metric": parsed.primaryIntensityMetric,
    }
