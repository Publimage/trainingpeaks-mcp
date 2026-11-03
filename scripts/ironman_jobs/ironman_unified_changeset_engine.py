"""Reusable, provider-independent change-set execution core.

The same engine processes a workout, a native note, an attachment, native
strength or a library item. Typed provider adapters own endpoint details.

This module does not import TrainingPeaks, connect to accounts or run jobs.
It is intentionally fail-closed until a separately approved adapter is wired.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

SCHEMA = "IRONMAN_CHANGESET_V1"
OWNER = 2116886
VALID_KINDS = frozenset({
    "plan.workout.patch",
    "plan.note.patch",
    "plan.note.attachment.add",
    "plan.note.attachment.retire",
    "plan.strength.relocate",
    "library.workout.patch",
})
VALID_STATES = frozenset({
    "PENDING", "RUNNING", "DONE_VERIFIED", "BLOCKED_SECURITY",
    "BLOCKED_CONFLICT", "FAILED_REVIEW", "UNKNOWN_NEEDS_READBACK",
    "SKIPPED_DEPENDENCY",
})
TOKEN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{2,119}$")
SHA = re.compile(r"^[a-f0-9]{64}$")


class ChangeStop(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class SecurityDenied(ChangeStop):
    """A real explicit authorization/security denial. NEVER retry elsewhere."""


class WriteUncertain(ChangeStop):
    """The adapter cannot prove whether the provider mutation completed."""


class Adapter(Protocol):
    def read(self, spec: dict[str, Any]) -> dict[str, Any]: ...
    def apply(self, spec: dict[str, Any]) -> None: ...


def need(test: bool, code: str) -> None:
    if not test:
        raise ChangeStop(code)


def digest(data: Any) -> str:
    return hashlib.sha256(json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_manifest(value: dict[str, Any]) -> str:
    """Strict enough to prevent accidental cross-plan/athlete writes."""
    need(type(value) is dict and set(value) == {
        "schema", "request_id", "owner_id", "reviewed_revision",
        "approval_scope", "changes",
    }, "MANIFEST_FIELDS")
    need(value["schema"] == SCHEMA, "MANIFEST_SCHEMA")
    need(value["owner_id"] == OWNER, "MANIFEST_OWNER")
    need(type(value["request_id"]) is str
         and TOKEN.fullmatch(value["request_id"]) is not None, "REQUEST_ID")
    need(type(value["approval_scope"]) is str
         and TOKEN.fullmatch(value["approval_scope"]) is not None, "APPROVAL_SCOPE")
    need(type(value["reviewed_revision"]) is str
         and re.fullmatch(r"[0-9a-f]{40}", value["reviewed_revision"]) is not None,
         "REVIEWED_REVISION")
    changes = value["changes"]
    need(type(changes) is list and 0 < len(changes) <= 1000, "CHANGE_COUNT")
    ids: set[str] = set()
    for item in changes:
        need(type(item) is dict and set(item) == {
            "id", "kind", "target", "before_sha256",
            "after_sha256", "depends_on", "payload",
        }, "CHANGE_FIELDS")
        change_id = item["id"]
        need(type(change_id) is str and TOKEN.fullmatch(change_id) is not None
             and change_id not in ids, "CHANGE_ID")
        ids.add(change_id)
        need(item["kind"] in VALID_KINDS, "UNKNOWN_ADAPTER")
        target = item["target"]
        need(type(target) is dict and set(target) == {
            "provider", "owner_id", "container_kind", "container_id", "resource_id",
        }, "TARGET_FIELDS")
        need(target["provider"] == "trainingpeaks"
             and target["owner_id"] == OWNER, "TARGET_OWNER")
        need(target["container_kind"] in ("training_plan", "workout_library"),
             "TARGET_CONTAINER")
        need(type(target["container_id"]) is int and target["container_id"] > 0
             and type(target["resource_id"]) is int and target["resource_id"] > 0,
             "TARGET_IDS")
        need((item["kind"].startswith("plan.") and target["container_kind"] == "training_plan")
             or (item["kind"].startswith("library.") and target["container_kind"] == "workout_library"),
             "TARGET_KIND_MISMATCH")
        need(type(item["before_sha256"]) is str
             and SHA.fullmatch(item["before_sha256"]) is not None
             and type(item["after_sha256"]) is str
             and SHA.fullmatch(item["after_sha256"]) is not None,
             "EXPECTED_DIGEST")
        need(type(item["payload"]) is dict, "PAYLOAD_SHAPE")
        deps = item["depends_on"]
        need(type(deps) is list and len(deps) == len(set(deps))
             and all(type(d) is str for d in deps)
             and change_id not in deps, "DEPENDENCY_SHAPE")
    need(all(d in ids for x in changes for d in x["depends_on"]),
         "DEPENDENCY_MISSING")
    graph = {x["id"]: x["depends_on"] for x in changes}
    visited: set[str] = set()
    visiting: set[str] = set()

    def walk(node: str) -> None:
        need(node not in visiting, "DEPENDENCY_CYCLE")
        if node in visited:
            return
        visiting.add(node)
        for dep in graph[node]:
            walk(dep)
        visiting.remove(node)
        visited.add(node)

    for change_id in graph:
        walk(change_id)
    # Multiple edits to one provider resource require explicit ordering.
    last_by_resource: dict[tuple[Any, ...], str] = {}
    for item in changes:
        target = item["target"]
        key = tuple(target[k] for k in (
            "provider", "owner_id", "container_kind", "container_id", "resource_id"
        ))
        previous = last_by_resource.get(key)
        need(previous is None or previous in item["depends_on"],
             "SHARED_RESOURCE_REQUIRES_DIRECT_DEPENDENCY")
        last_by_resource[key] = item["id"]
    return digest(value)


class Ledger:
    """Crash-persistent SQLite event state and resource claims, no shell access.

    Resource claims are NOT auto-expired: after a crash, human/provider
    reconciliation is required before reassigning a possibly modified item.
    """
    def __init__(self, path: Path):
        self.path = Path(path)
        self.db = sqlite3.connect(str(self.path), timeout=8)
        self.db.execute("PRAGMA busy_timeout=8000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS requests (
              request_id TEXT PRIMARY KEY, manifest_sha TEXT NOT NULL,
              created_utc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS change_events (
              request_id TEXT NOT NULL, change_id TEXT NOT NULL,
              state TEXT NOT NULL, provider_sha TEXT,
              observed_utc TEXT NOT NULL, reason TEXT,
              PRIMARY KEY(request_id, change_id));
            CREATE TABLE IF NOT EXISTS resource_claims (
              resource_key TEXT PRIMARY KEY,
              request_id TEXT NOT NULL, change_id TEXT NOT NULL);
        """)

    def close(self) -> None:
        self.db.close()

    def setup(self, manifest: dict[str, Any], manifest_sha: str) -> None:
        request = manifest["request_id"]
        # Lock before reading the request row. Without BEGIN IMMEDIATE two
        # concurrent callers can both observe an absent row and race on INSERT,
        # turning an idempotent replay into an IntegrityError.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute(
                "SELECT manifest_sha FROM requests WHERE request_id=?", (request,)
            ).fetchone()
            if existing:
                need(existing[0] == manifest_sha, "IDEMPOTENCY_MANIFEST_DRIFT")
            else:
                self.db.execute("INSERT INTO requests VALUES (?,?,?)",
                                (request, manifest_sha, utc()))
                for item in manifest["changes"]:
                    self.db.execute("INSERT INTO change_events VALUES (?,?,?,?,?,?)",
                                    (request, item["id"], "PENDING", None, utc(), None))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def status(self, request: str, change_id: str) -> str:
        row = self.db.execute(
            "SELECT state FROM change_events WHERE request_id=? AND change_id=?",
            (request, change_id),
        ).fetchone()
        need(row is not None, "LEDGER_MISSING_CHANGE")
        return row[0]

    def set_state(self, request: str, change_id: str, state: str,
                  provider_sha: str | None = None, reason: str | None = None) -> None:
        need(state in VALID_STATES, "LEDGER_INVALID_STATE")
        with self.db:
            self.db.execute(
                """UPDATE change_events
                   SET state=?, provider_sha=?, observed_utc=?, reason=?
                   WHERE request_id=? AND change_id=?""",
                (state, provider_sha, utc(), reason, request, change_id),
            )

    def claim(self, request: str, item: dict[str, Any]) -> None:
        target = item["target"]
        key = ":".join(str(x) for x in (
            target["provider"], target["owner_id"], target["container_kind"],
            target["container_id"], target["resource_id"],
        ))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT request_id,change_id FROM resource_claims WHERE resource_key=?",
                (key,),
            ).fetchone()
            need(row is None or row == (request, item["id"]),
                 "RESOURCE_CLAIMED_BY_OTHER_CHANGE")
            if row is None:
                self.db.execute("INSERT INTO resource_claims VALUES (?,?,?)",
                                (key, request, item["id"]))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def release(self, request: str, item: dict[str, Any]) -> None:
        target = item["target"]
        key = ":".join(str(x) for x in (
            target["provider"], target["owner_id"], target["container_kind"],
            target["container_id"], target["resource_id"],
        ))
        with self.db:
            self.db.execute(
                "DELETE FROM resource_claims WHERE resource_key=? AND request_id=? AND change_id=?",
                (key, request, item["id"]),
            )


def run_changeset(
    manifest: dict[str, Any],
    adapters: Mapping[str, Adapter],
    ledger: Ledger,
    *,
    execute: bool = False,
    reviewed_revision: str | None = None,
    approval_scope: str | None = None,
) -> dict[str, Any]:
    """One common route for all resource kinds, never implicit write.

    If an attempted provider write is ambiguous or explicitly denied,
    reconcile its state and STOP only that resource and dependent changes.
    Independent changes continue. No retry loops and no credential fallback.
    """
    manifest_sha = validate_manifest(manifest)
    if execute:
        # A machine-generated preview marker is never an independent approval.
        need(not manifest["approval_scope"].startswith("PREVIEW_ONLY:"),
             "PREVIEW_DRAFT_NOT_APPROVED")
        need(reviewed_revision == manifest["reviewed_revision"], "REVISION_NOT_APPROVED")
        need(approval_scope == manifest["approval_scope"], "SCOPE_NOT_APPROVED")
    ledger.setup(manifest, manifest_sha)
    ordered = []
    by_id = {x["id"]: x for x in manifest["changes"]}
    pending = set(by_id)
    while pending:
        ready = [x for x in manifest["changes"] if x["id"] in pending
                 and all(d not in pending for d in x["depends_on"])]
        need(bool(ready), "DAG_STALLED")
        for x in ready:
            ordered.append(x)
            pending.remove(x["id"])
    outcomes = []
    preview_passed: set[str] = set()
    preview_images: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in ordered:
        name, kind = item["id"], item["kind"]
        target = item["target"]
        resource_key = tuple(target[k] for k in (
            "provider", "owner_id", "container_kind", "container_id", "resource_id"
        ))
        state = ledger.status(manifest["request_id"], name)
        if state == "SKIPPED_DEPENDENCY" and execute:
            # Migrate an item skipped by an older ledger implementation.
            # Revalidation below still requires every dependency, preimage
            # and explicit scope before any provider mutation.
            ledger.set_state(manifest["request_id"], name, "PENDING",
                             reason="LEGACY_DEPENDENCY_DEFERRAL_RECOVERED")
            state = "PENDING"
        if state == "DONE_VERIFIED":
            # The ledger is not the provider source of truth. A resumed flow
            # must recheck the actual object before it claims verification.
            adapter = adapters.get(kind)
            if adapter is None:
                if execute:
                    ledger.set_state(manifest["request_id"], name,
                                     "UNKNOWN_NEEDS_READBACK",
                                     reason="VERIFIED_ITEM_ADAPTER_NOT_INSTALLED")
                outcomes.append({"id": name, "state": "UNKNOWN_NEEDS_READBACK",
                                 "code": "ADAPTER_NOT_INSTALLED"})
                continue
            try:
                observed = adapter.read(item)
                live_sha = digest(observed)
            except Exception:
                # Never let dependent writes rely on a receipt that we cannot
                # re-confirm on the provider during this execution.
                if execute:
                    ledger.set_state(manifest["request_id"], name,
                                     "UNKNOWN_NEEDS_READBACK",
                                     reason="VERIFIED_ITEM_READBACK_FAILED")
                outcomes.append({"id": name, "state": "UNKNOWN_NEEDS_READBACK",
                                 "code": "VERIFIED_ITEM_READBACK_FAILED"})
                continue
            # A verified change may have been intentionally superseded by a
            # later, verified change on the SAME note/workout. Compare the
            # provider with the allowed final chain, not a stale mid-state.
            acceptable_shas = {item["after_sha256"]}
            later = False
            for next_item in ordered:
                if next_item["id"] == name:
                    later = True
                    continue
                if not later:
                    continue
                next_t = next_item["target"]
                next_key = tuple(next_t[k] for k in (
                    "provider", "owner_id", "container_kind",
                    "container_id", "resource_id"
                ))
                if next_key == resource_key and ledger.status(
                        manifest["request_id"], next_item["id"]
                ) in {"DONE_VERIFIED", "UNKNOWN_NEEDS_READBACK", "RUNNING"}:
                    acceptable_shas.add(next_item["after_sha256"])
            if live_sha not in acceptable_shas:
                if execute:
                    ledger.set_state(manifest["request_id"], name,
                                     "BLOCKED_CONFLICT", provider_sha=live_sha,
                                     reason="POST_VERIFIED_PROVIDER_DRIFT")
                outcomes.append({"id": name, "state": "BLOCKED_CONFLICT",
                                 "code": "POST_VERIFIED_PROVIDER_DRIFT"})
                continue
            outcomes.append({"id": name, "state": "DONE_VERIFIED",
                             "source": "provider_rechecked"})
            if not execute:
                preview_passed.add(name)
                preview_images[resource_key] = observed
            continue
        if state in ("UNKNOWN_NEEDS_READBACK", "RUNNING"):
            # A timed-out mutation or process crash is reconciled by READ only.
            # Never replay a potentially completed provider operation.
            adapter = adapters.get(kind)
            try:
                observed_sha = digest(adapter.read(item)) if adapter else None
            except Exception:
                observed_sha = None
            # A previous verified edit can have been superseded by a later
            # verified edit to the SAME resource. Reconcile against its final
            # verified image too; never replay either write.
            accepted_shas = {item["after_sha256"]}
            passed_self = False
            for next_item in ordered:
                if next_item["id"] == name:
                    passed_self = True
                    continue
                if not passed_self:
                    continue
                next_t = next_item["target"]
                next_key = tuple(next_t[k] for k in (
                    "provider", "owner_id", "container_kind",
                    "container_id", "resource_id"
                ))
                if (next_key == resource_key
                        and ledger.status(manifest["request_id"], next_item["id"])
                        == "DONE_VERIFIED"):
                    accepted_shas.add(next_item["after_sha256"])
            if observed_sha is not None and observed_sha in accepted_shas:
                if execute:
                    ledger.set_state(manifest["request_id"], name,
                                     "DONE_VERIFIED", provider_sha=observed_sha)
                    ledger.release(manifest["request_id"], item)
                outcomes.append({"id": name, "state": "DONE_VERIFIED",
                                 "source": "provider_reconciled_on_resume"})
                if not execute:
                    preview_passed.add(name)
            else:
                if execute and state == "RUNNING":
                    ledger.set_state(manifest["request_id"], name,
                                     "UNKNOWN_NEEDS_READBACK",
                                     provider_sha=observed_sha,
                                     reason="CRASH_OR_WRITE_OUTCOME_NOT_VERIFIED")
                outcomes.append({"id": name, "state": "UNKNOWN_NEEDS_READBACK",
                                 "code": "RECONCILIATION_REQUIRED"})
            continue
        if state not in ("PENDING",):
            outcomes.append({"id": name, "state": state, "code": "RECONCILIATION_REQUIRED"})
            continue
        if any((ledger.status(manifest["request_id"], d) != "DONE_VERIFIED")
               if execute else (d not in preview_passed)
               for d in item["depends_on"]):
            # Dependency deferral is NOT a terminal state: keep PENDING in
            # the durable ledger so this item runs after safe reconciliation.
            outcomes.append({"id": name, "state": "SKIPPED_DEPENDENCY",
                             "code": "WAITING_FOR_DEPENDENCY"})
            continue
        adapter = adapters.get(kind)
        if adapter is None:
            if execute:
                ledger.set_state(manifest["request_id"], name, "FAILED_REVIEW",
                                 reason="ADAPTER_NOT_INSTALLED")
            outcomes.append({"id": name, "state": "FAILED_REVIEW",
                             "code": "ADAPTER_NOT_INSTALLED"})
            continue
        try:
            try:
                current = (preview_images[resource_key]
                           if not execute and resource_key in preview_images
                           else adapter.read(item))
            except SecurityDenied:
                # An explicit denial remains an authorization stop.
                raise
            except ChangeStop as error:
                # The live TP reader reports transient/non-specific provider
                # read errors as ChangeStop. Treat ONLY these read errors as
                # deferred, never as approved retries or provider writes.
                if error.code not in {
                    "WORKOUT_WINDOW_FAILED", "LIBRARY_READ_FAILED",
                    "TRAINING_PLAN_READ_FAILED", "PLAN_NOTES_READ_FAILED",
                    "STRENGTH_READ_FAILED",
                }:
                    raise
                outcomes.append({"id": name, "state": "PENDING",
                                 "code": "PROVIDER_PREFLIGHT_READ_UNAVAILABLE",
                                 "read_code": error.code})
                continue
            except Exception:
                # A temporary READ failure has not attempted a provider write.
                # Do not abort unrelated resources or mark this item complete.
                outcomes.append({"id": name, "state": "PENDING",
                                 "code": "PROVIDER_PREFLIGHT_READ_FAILED"})
                continue
            before = digest(current)
            if before == item["after_sha256"]:
                if not execute:
                    preview_passed.add(name)
                    preview_images[resource_key] = current
                if execute:
                    ledger.set_state(manifest["request_id"], name,
                                     "DONE_VERIFIED", provider_sha=before)
                outcomes.append({"id": name, "state": "DONE_VERIFIED",
                                 "source": "provider_already_target"})
                continue
            if before != item["before_sha256"]:
                if execute:
                    ledger.set_state(manifest["request_id"], name, "BLOCKED_CONFLICT",
                                     provider_sha=before, reason="PREIMAGE_DRIFT")
                outcomes.append({"id": name, "state": "BLOCKED_CONFLICT",
                                 "code": "PREIMAGE_DRIFT"})
                continue
            validator = getattr(adapter, "validate", None)
            if callable(validator):
                validator(item, current)
            if not execute:
                desired = item["payload"].get("desired")
                if isinstance(desired, dict) and digest(desired) == item["after_sha256"]:
                    preview_images[resource_key] = desired
                else:
                    preview_images.pop(resource_key, None)
                preview_passed.add(name)
                outcomes.append({"id": name, "state": "PREFLIGHT_PASS"})
                continue
            ledger.claim(manifest["request_id"], item)
            ledger.set_state(manifest["request_id"], name, "RUNNING",
                             provider_sha=before)
            def safe_readback_sha() -> str | None:
                try:
                    return digest(adapter.read(item))
                except Exception:
                    return None
            try:
                adapter.apply(item)
            except SecurityDenied:
                after = safe_readback_sha()
                ledger.set_state(manifest["request_id"], name,
                                 "BLOCKED_SECURITY", provider_sha=after,
                                 reason="PROVIDER_DENIAL_NO_RETRY")
                if after is not None:
                    ledger.release(manifest["request_id"], item)
                outcomes.append({"id": name, "state": "BLOCKED_SECURITY"})
                continue
            except Exception:
                # Even if the transport timed out, mutation might have succeeded.
                after = safe_readback_sha()
                if after == item["after_sha256"]:
                    ledger.set_state(manifest["request_id"], name,
                                     "DONE_VERIFIED", provider_sha=after)
                    ledger.release(manifest["request_id"], item)
                    outcomes.append({"id": name, "state": "DONE_VERIFIED",
                                     "source": "provider_reconciled"})
                else:
                    ledger.set_state(manifest["request_id"], name,
                                     "UNKNOWN_NEEDS_READBACK", provider_sha=after,
                                     reason="WRITE_OUTCOME_UNCERTAIN_NO_RETRY")
                    outcomes.append({"id": name, "state": "UNKNOWN_NEEDS_READBACK"})
                continue
            after = safe_readback_sha()
            if after != item["after_sha256"]:
                ledger.set_state(manifest["request_id"], name,
                                 "UNKNOWN_NEEDS_READBACK", provider_sha=after,
                                 reason="POSTFLIGHT_MISMATCH")
                outcomes.append({"id": name, "state": "UNKNOWN_NEEDS_READBACK"})
            else:
                ledger.set_state(manifest["request_id"], name,
                                 "DONE_VERIFIED", provider_sha=after)
                ledger.release(manifest["request_id"], item)
                outcomes.append({"id": name, "state": "DONE_VERIFIED",
                                 "source": "provider_postflight"})
        except SecurityDenied:
            if execute:
                ledger.set_state(manifest["request_id"], name, "BLOCKED_SECURITY")
            outcomes.append({"id": name, "state": "BLOCKED_SECURITY"})
        except ChangeStop as error:
            if execute:
                ledger.set_state(manifest["request_id"], name, "FAILED_REVIEW",
                                 reason=error.code)
            outcomes.append({"id": name, "state": "FAILED_REVIEW", "code": error.code})
    # A green technical preflight is never the original request's completion.
    # Only a write run whose every item is provider-verified may finish.
    complete = bool(execute and len(outcomes) == len(ordered)
                    and all(row["state"] == "DONE_VERIFIED" for row in outcomes))
    return {
        "schema": "IRONMAN_CHANGESET_RESULT_V1", "request_id": manifest["request_id"],
        "manifest_sha256": manifest_sha, "mode": "execute" if execute else "preview",
        "request_state": ("WORK_COMPLETE" if complete else
                          "PREVIEW_ONLY" if not execute else "ACTION_INCOMPLETE"),
        "provider_readback_verified": complete,
        "results": outcomes,
        "provider_writes_claimed": sum(
            x["state"] == "DONE_VERIFIED" and x.get("source") == "provider_postflight"
            for x in outcomes),
    }
