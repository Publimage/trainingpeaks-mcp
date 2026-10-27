"""Common, provider-agnostic safety and recovery engine for Training Plan workout patches.

This module does not expose an MCP tool and cannot select a TrainingPeaks account,
invoke a provider, or authorize itself. A reviewed job must supply the provider
gateway, an immutable reviewed manifest digest, and the exact approved scope.

Existing endpoint-specific publishers can migrate to this engine incrementally.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Protocol

from scripts.ironman_jobs.ironman_file_lock import FileLockBusy, exclusive_file_lock


SCHEMA = "IRONMAN_PLAN_PATCH_V1"
ALLOWED = {"title", "description", "totalTimePlanned", "distancePlanned", "structure"}
MAX_ITEMS = 150


class PlanPatchStop(RuntimeError):
    """No automatic replay is permitted after this exception."""


class PlanGateway(Protocol):
    async def get_owner_id(self) -> int: ...
    async def get_plan(self, plan_id: int) -> dict[str, Any]: ...
    async def get_workout(self, plan_id: int, workout_id: int) -> dict[str, Any]: ...
    async def put_workout(
        self, plan_id: int, workout_id: int, payload: dict[str, Any]
    ) -> Any: ...


def require(condition: bool, code: str) -> None:
    if not condition:
        raise PlanPatchStop(code)


def canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def validate_patch_fields(before: dict[str, Any], after: dict[str, Any]) -> None:
    """Validate a selected-field delta without inventing plan metadata.

    Shared by the reviewed batch publisher and the typed ChangeSet adapter.
    This pure function grants no permission and does not modify its inputs.
    """
    require(isinstance(before, dict) and isinstance(after, dict)
            and bool(after) and before.keys() == after.keys(), "FIELD_SET_MISMATCH")
    require(set(after).issubset(ALLOWED), "FIELD_NOT_PERMITTED")
    for field, value in after.items():
        if field in {"title", "description"}:
            require(isinstance(value, str) and bool(value.strip()), "EMPTY_TEXT")
            if field == "title":
                require(len(value) <= 255, "TITLE_TOO_LONG")
            if field == "description":
                require("\\n" not in value, "LITERAL_NEWLINE_ESCAPE")
        if field in {"distancePlanned", "totalTimePlanned"}:
            require(type(value) in {int, float} and 0 < value < 10000000,
                    "BAD_POSITIVE_PLANNED_VALUE")
        if field == "structure":
            require(isinstance(value, dict) and isinstance(value.get("structure"), list)
                    and bool(value["structure"]), "BUILDER_STRUCTURE_REQUIRED")
            require(bool(value.get("polyline")), "BUILDER_POLYLINE_REQUIRED")
    require(before != after, "NO_CHANGE_ITEM")


def validate_manifest(manifest: dict[str, Any]) -> str:
    require(isinstance(manifest, dict), "MANIFEST_REQUIRED")
    require(manifest.get("schema") == SCHEMA, "MANIFEST_SCHEMA")
    require(type(manifest.get("owner_id")) is int and manifest["owner_id"] > 0, "OWNER")
    require(type(manifest.get("plan_id")) is int and manifest["plan_id"] > 0, "PLAN_ID")
    require(isinstance(manifest.get("expected_title"), str)
            and bool(manifest["expected_title"].strip()), "PLAN_TITLE")
    require(type(manifest.get("expected_is_public")) is bool, "PLAN_VISIBILITY")
    require(type(manifest.get("expected_workout_count")) is int
            and manifest["expected_workout_count"] > 0, "PLAN_COUNT")
    require(isinstance(manifest.get("scope"), str)
            and len(manifest["scope"]) >= 12, "APPROVED_SCOPE")
    items = manifest.get("items")
    require(isinstance(items, list) and 1 <= len(items) <= MAX_ITEMS, "ITEM_COUNT")
    ids: set[int] = set()
    for row in items:
        require(isinstance(row, dict), "ITEM_NOT_OBJECT")
        wid = row.get("workout_id")
        require(type(wid) is int and wid > 0 and wid not in ids, "DUPLICATE_OR_BAD_ID")
        ids.add(wid)
        before, after = row.get("before"), row.get("after")
        validate_patch_fields(before, after)
    return sha256(manifest)


def selected(source: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    return {name: source.get(name) for name in fields}


def assert_provider_scope(meta: dict[str, Any], manifest: dict[str, Any]) -> None:
    require(meta.get("planId") == manifest["plan_id"], "PLAN_ID_CHANGED")
    require(meta.get("title") == manifest["expected_title"], "PLAN_TITLE_CHANGED")
    require(meta.get("isPublic") is manifest["expected_is_public"], "PLAN_VISIBILITY_CHANGED")
    require(meta.get("workoutCount") == manifest["expected_workout_count"],
            "PLAN_COUNT_CHANGED")


def assert_workout_identity(row: dict[str, Any], workout: dict[str, Any]) -> None:
    require(workout.get("workoutId") == row["workout_id"], "WORKOUT_ID_CHANGED")


def intended_payload(workout: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(workout)
    payload.update(copy.deepcopy(row["after"]))
    if workout.get("workoutTypeValueId") == 1:
        require(type(payload.get("distancePlanned")) in {int, float}
                and payload["distancePlanned"] > 0, "SWIM_DISTANCE_REQUIRED")
        require(type(payload.get("totalTimePlanned")) in {int, float}
                and payload["totalTimePlanned"] > 0, "SWIM_DURATION_REQUIRED")
    return payload


def _read_journal(path: Path, digest: str, manifest: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return {"schema": "IRONMAN_PLAN_PATCH_JOURNAL_V1", "manifest_sha256": digest,
                "scope": manifest["scope"], "plan_id": manifest["plan_id"],
                "items": {}, "originals": {}}
    require(not path.is_symlink(), "JOURNAL_SYMLINK")
    data = json.loads(path.read_text(encoding="utf-8"))
    require(data.get("schema") == "IRONMAN_PLAN_PATCH_JOURNAL_V1"
            and data.get("manifest_sha256") == digest
            and data.get("scope") == manifest["scope"]
            and data.get("plan_id") == manifest["plan_id"], "JOURNAL_MANIFEST_CONFLICT")
    require(isinstance(data.get("items"), dict)
            and isinstance(data.get("originals"), dict), "JOURNAL_CORRUPT")
    return data


def _persist(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(not path.parent.is_symlink() and not path.is_symlink(), "UNSAFE_JOURNAL_PATH")
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=".planpatch-", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(canonical(data) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


async def _run_batch_unlocked(
    manifest: dict[str, Any], gateway: PlanGateway, journal_path: Path,
    *, execute: bool = False, ack_scope: str | None = None,
    reviewed_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Default preview is read-only. Execute is allowlisted by a reviewed manifest.

    If a PUT has an ambiguous outcome, read back once. If the desired state is
    not proven, leave the item UNCERTAIN and stop; never blindly replay.
    """
    digest = validate_manifest(manifest)
    require(not execute or reviewed_manifest_sha256 == digest, "MANIFEST_NOT_REVIEWED")
    require(not execute or ack_scope == manifest["scope"], "SCOPE_NOT_ACKNOWLEDGED")
    require(await gateway.get_owner_id() == manifest["owner_id"], "OWNER_MISMATCH")
    meta = await gateway.get_plan(manifest["plan_id"])
    assert_provider_scope(meta, manifest)
    path = Path(journal_path)
    ledger = _read_journal(path, digest, manifest) if execute else None
    results: list[dict[str, Any]] = []
    for row in manifest["items"]:
        wid = row["workout_id"]
        key = str(wid)
        current = await gateway.get_workout(manifest["plan_id"], wid)
        assert_workout_identity(row, current)
        actual = selected(current, row["after"])
        original = row["before"]
        desired = row["after"]
        previous = ledger["items"].get(key) if execute else None
        if actual == desired:
            status = "ALREADY_VERIFIED"
            if execute:
                ledger["items"][key] = "VERIFIED"
                _persist(path, ledger)
        else:
            require(actual == original, "TARGET_DRIFT_" + key)
            intended_payload(current, row)  # Validate the complete proposed workout.
            if not execute:
                status = "READY"
            else:
                require(previous not in {"INTENT", "UNCERTAIN", "REVIEW_REQUIRED"}, "RECONCILE_FIRST")
                # Record complete provider backup *before* changing this item.
                ledger["originals"].setdefault(key, copy.deepcopy(current))
                ledger["items"][key] = "INTENT"
                _persist(path, ledger)
                proposed = intended_payload(current, row)
                try:
                    response = await gateway.put_workout(manifest["plan_id"], wid, proposed)
                    if response is False:
                        raise PlanPatchStop("PROVIDER_REJECTED_" + key)
                except Exception:
                    # A transient error can conceal a successful provider write.
                    try:
                        check = await gateway.get_workout(manifest["plan_id"], wid)
                        proven = (check.get("workoutId") == wid
                                  and selected(check, desired) == desired)
                    except Exception:
                        proven = False
                    if not proven:
                        ledger["items"][key] = "UNCERTAIN"
                        _persist(path, ledger)
                        raise PlanPatchStop("UNCERTAIN_RESULT_READBACK_REQUIRED_" + key)
                check = await gateway.get_workout(manifest["plan_id"], wid)
                require(check.get("workoutId") == wid
                        and selected(check, desired) == desired,
                        "POST_WRITE_NOT_VERIFIED_" + key)
                ledger["items"][key] = "VERIFIED"
                _persist(path, ledger)
                status = "VERIFIED"
        results.append({"workout_id": wid, "status": status})
    again = await gateway.get_plan(manifest["plan_id"])
    assert_provider_scope(again, manifest)
    if execute:
        for row in manifest["items"]:
            item = await gateway.get_workout(manifest["plan_id"], row["workout_id"])
            require(selected(item, row["after"]) == row["after"],
                    "FINAL_READBACK_FAILED_" + str(row["workout_id"]))
    return {"status": "VERIFIED" if execute else "PREVIEW",
            "plan_id": manifest["plan_id"], "manifest_sha256": digest,
            "processed": len(results), "items": results,
            "provider_writes": sum(x["status"] == "VERIFIED" for x in results),
            "scope": manifest["scope"]}


@contextmanager
def _exclusive_run(path: Path):
    """Keep a cross-process lock for the complete provider mutation batch."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(not path.parent.is_symlink(), "UNSAFE_LOCK_PARENT")
    os.chmod(path.parent, 0o700)
    lock_path = path.parent / (path.name + ".lock")
    try:
        with exclusive_file_lock(lock_path):
            yield
    except FileLockBusy as exc:
        raise PlanPatchStop("ANOTHER_PLAN_BATCH_RUNNING") from exc


async def run_batch(
    manifest: dict[str, Any], gateway: PlanGateway, journal_path: Path,
    *, execute: bool = False, ack_scope: str | None = None,
    reviewed_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Serialize mutating runs; previews are deliberately read-only."""
    if not execute:
        return await _run_batch_unlocked(
            manifest, gateway, journal_path, execute=False,
            ack_scope=ack_scope, reviewed_manifest_sha256=reviewed_manifest_sha256
        )
    with _exclusive_run(Path(journal_path)):
        return await _run_batch_unlocked(
            manifest, gateway, journal_path, execute=True,
            ack_scope=ack_scope, reviewed_manifest_sha256=reviewed_manifest_sha256
        )


__all__ = ["PlanPatchStop", "PlanGateway", "validate_manifest", "sha256",
           "run_batch", "intended_payload", "validate_patch_fields"]
