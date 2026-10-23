"""Reusable Training Plan classic-workout patch adapter for ChangeSet V1.

Only existing native Training Plan copies: no athlete calendars, library updates,
or new workouts. Selected field syntax is delegated to the existing proven
plan_patch_batch_core validator; actual provider writes require a separately
reviewed gateway, injected per operation after approval and canary. No new API.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    OWNER, ChangeStop, SecurityDenied, digest, need,
)
from scripts.ironman_jobs.plan_patch_batch_core import (
    ALLOWED, PlanPatchStop, validate_manifest,
)
from scripts.ironman_jobs.ironman_unified_trainingpeaks_reads import (
    TrainingPeaksReadOnlyAdapter,
)


def validate_classic_patch(change: dict[str, Any], current: dict[str, Any]) -> tuple[int, int]:
    need(change.get("kind") == "plan.workout.patch", "NOT_PLAN_WORKOUT_KIND")
    target = change.get("target")
    need(isinstance(target, dict) and target.get("provider") == "trainingpeaks"
         and target.get("owner_id") == OWNER
         and target.get("container_kind") == "training_plan",
         "CLASSIC_TARGET_NOT_PLAN")
    plan_id, workout_id = target.get("container_id"), target.get("resource_id")
    need(type(plan_id) is int and plan_id > 0
         and type(workout_id) is int and workout_id > 0, "CLASSIC_IDS")
    need(type(current) is dict and current.get("workoutId") == workout_id,
         "CLASSIC_WORKOUT_IDENTITY")
    payload = change.get("payload")
    need(type(payload) is dict and set(payload) == {"desired", "fields"},
         "CLASSIC_PATCH_PAYLOAD")
    desired, fields = payload["desired"], payload["fields"]
    need(type(desired) is dict and type(fields) is list
         and 1 <= len(fields) <= len(ALLOWED)
         and len(fields) == len(set(fields))
         and all(type(k) is str and k in ALLOWED for k in fields),
         "CLASSIC_FIELDS_NOT_ALLOWED")
    expected = deepcopy(current)
    for field in fields:
        need(field in desired, "CLASSIC_FIELD_MISSING")
        expected[field] = desired[field]
    need(expected == desired, "CLASSIC_UNREVIEWED_FIELDS_CHANGED")
    before_fields = {key: current.get(key) for key in fields}
    after_fields = {key: desired[key] for key in fields}
    # Reuse the existing reviewed publisher's tested field/Builder validator.
    # The synthetic plan summary here is ONLY for field-shape validation; it
    # never acts as live plan metadata or as authorization to publish.
    try:
        validate_manifest({
            "schema": "IRONMAN_PLAN_PATCH_V1", "owner_id": OWNER,
            "plan_id": plan_id, "expected_title": "FIELD_VALIDATION_ONLY",
            "expected_is_public": False, "expected_workout_count": 1,
            "scope": f"trainingpeaks:plan:{plan_id}:field-validator-only",
            "items": [{"workout_id": workout_id,
                       "before": before_fields, "after": after_fields}],
        })
    except PlanPatchStop as exc:
        raise ChangeStop("CLASSIC_FIELDS_INVALID:" + str(exc)) from exc
    need(change.get("before_sha256") == digest(current)
         and change.get("after_sha256") == digest(desired),
         "CLASSIC_REVIEW_HASH_DRIFT")
    return plan_id, workout_id


class ReviewedClassicPlanPatchAdapter:
    def __init__(self, *, reader: Any = None,
                 put_one: Callable[[int, int, dict[str, Any]], None] | None = None):
        self.reader = reader if reader is not None else TrainingPeaksReadOnlyAdapter()
        self.put_one = put_one

    def read(self, change: dict[str, Any]) -> dict[str, Any]:
        return self.reader.read(change)

    def validate(self, change: dict[str, Any], current: dict[str, Any]) -> None:
        validate_classic_patch(change, current)

    def apply(self, change: dict[str, Any]) -> None:
        if self.put_one is None:
            raise SecurityDenied("CLASSIC_PLAN_WRITER_NOT_ACTIVATED")
        # A reviewed publisher must inject its proven, guarded PUT callback.
        # The adapter never chooses an endpoint or expands a plan scope.
        current = self.read(change)
        plan_id, workout_id = validate_classic_patch(change, current)
        self.put_one(plan_id, workout_id, deepcopy(change["payload"]["desired"]))
