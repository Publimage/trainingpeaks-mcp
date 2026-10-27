"""Persist individually scoped, typed IRONMAN operation drafts across chats.

Request preparation does not access providers or grant authorization. The
existing trusted TrainingPeaks reader and operation-specific writer MUST recheck
current permissions, owner, container membership and hashes before writing.
The draft database is hosted in the EXISTING Prefect service, never GitHub.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA = "IRONMAN_OPERATION_DRAFT_V1"
OWNER = 2116886
MAX_ITEMS = 500
MAX_BYTES = 1_500_000
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,119}$")
SHA = re.compile(r"^[a-f0-9]{64}$")

# Adapter readiness, never publication permission. New classes are deliberately
# blocked until their independent per-kind canary and provider readback.
KINDS: dict[str, tuple[str, str, str]] = {
    "plan.create": ("training_plan", "new_container", "UNVERIFIED_WRITER"),
    "plan.copy": ("training_plan", "existing_container", "PROVEN_SCOPED"),
    "plan.workout.create": ("training_plan", "new_item", "UNVERIFIED_WRITER"),
    "plan.workout.patch": ("training_plan", "existing_item", "PROVEN_SCOPED"),
    "plan.workout.delete": ("training_plan", "existing_item", "UNVERIFIED_WRITER"),
    "plan.note.create": ("training_plan", "new_item", "PROVEN_SCOPED"),
    "plan.note.patch": ("training_plan", "existing_item", "CONDITIONAL"),
    "plan.note.attachment.add": ("training_plan", "existing_item", "PROVEN_SCOPED"),
    "plan.note.attachment.retire": ("training_plan", "existing_item", "PROVEN_SCOPED"),
    "plan.strength.relocate": ("training_plan", "existing_item", "CONDITIONAL"),
    "library.workout.create": ("workout_library", "new_item", "PROVEN_SCOPED"),
    "library.workout.patch": ("workout_library", "existing_item", "CONDITIONAL"),
    "athlete.workout.create": ("athlete_calendar", "new_item", "PROVEN_SCOPED"),
    "athlete.workout.patch": ("athlete_calendar", "existing_item", "PROVEN_SCOPED"),
    "athlete.workout.delete": ("athlete_calendar", "existing_item", "PROVEN_SCOPED"),
}


class DraftStop(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise DraftStop(code)


def canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DraftStop("DRAFT_JSON_INVALID") from exc


def _positive(value: Any) -> bool:
    return type(value) is int and 0 < value < 2**63


def _scan_payload(value: Any, depth: int = 0) -> None:
    require(depth <= 12, "PAYLOAD_DEPTH_LIMIT")
    if type(value) is dict:
        require(len(value) <= 200 and all(type(k) is str and len(k) <= 80
                                         for k in value), "PAYLOAD_KEYS_INVALID")
        for key, val in value.items():
            # Credentials or signed source URLs must never enter the draft log.
            keyname = key.lower().replace("-", "_")
            require(not any(word in keyname for word in (
                "token", "secret", "password", "cookie", "authorization",
                "signed_url", "source_url", "api_key", "credential", "url", "uri",
            )), "SECRET_BEARING_FIELD")
            _scan_payload(val, depth + 1)
    elif type(value) is list:
        require(len(value) <= 2000, "PAYLOAD_ITEMS_LIMIT")
        for val in value:
            _scan_payload(val, depth + 1)
    else:
        require(value is None or type(value) in (str, bool, int, float),
                "PAYLOAD_TYPE_INVALID")
        if type(value) is str:
            require(len(value) <= 100000, "PAYLOAD_STRING_LIMIT")
            require(not value.strip().lower().startswith(("http://", "https://", "bearer ")),
                    "PAYLOAD_DIRECT_URL_OR_CREDENTIAL")


def prepare_draft(items: list[dict[str, Any]], *, owner_id: int = OWNER,
                  request_key: str | None = None) -> dict[str, Any]:
    """Create one deterministic, non-executable multi-resource request.

    A stable request_key from the submitting operation allows safe retries;
    a changed payload with the same key is rejected by DraftStore. Without a
    key, the semantic hash serves as a stable retry identity. Provider state
    hashes must come from fresh independent reads, not a prior plan manifest.
    """
    require(type(owner_id) is int and owner_id == OWNER, "OWNER_MISMATCH")
    require(type(items) is list and 0 < len(items) <= MAX_ITEMS, "ITEM_COUNT")
    require(request_key is None or (type(request_key) is str and
            TOKEN.fullmatch(request_key) is not None), "REQUEST_KEY_INVALID")
    seen_ids: set[str] = set()
    seen_resource: dict[tuple[Any, ...], str] = {}
    normalized: list[dict[str, Any]] = []
    for item in items:
        require(type(item) is dict and set(item) == {
            "id", "kind", "target", "payload", "before_sha256", "depends_on",
        }, "ITEM_FIELDS")
        change_id, kind, target = item["id"], item["kind"], item["target"]
        require(type(change_id) is str and TOKEN.fullmatch(change_id) is not None
                and change_id not in seen_ids, "CHANGE_ID")
        seen_ids.add(change_id)
        require(type(kind) is str and kind in KINDS, "KIND_UNSUPPORTED")
        container_kind, presence, _ = KINDS[kind]
        base_target_fields = {
            "provider", "owner_id", "container_kind", "container_id", "resource_id",
        }
        require(type(target) is dict and
                base_target_fields.issubset(target) and
                set(target).issubset(base_target_fields | {"container_ref", "resource_ref"}),
                "TARGET_FIELDS")
        require(target["provider"] == "trainingpeaks" and
                type(target["owner_id"]) is int and target["owner_id"] == OWNER and
                target["container_kind"] == container_kind, "TARGET_MISMATCH")
        container_id, resource_id = target["container_id"], target["resource_id"]
        container_ref = target.get("container_ref")
        resource_ref = target.get("resource_ref")
        require(container_ref is None or
                (type(container_ref) is str and TOKEN.fullmatch(container_ref) is not None),
                "CONTAINER_REF_INVALID")
        require(resource_ref is None or
                (type(resource_ref) is str and TOKEN.fullmatch(resource_ref) is not None),
                "RESOURCE_REF_INVALID")
        # A reference is a dependency, not an invented provider ID. Any actual
        # create/copy result must later be bound to a real ID by a separately
        # approved adapter with independent provider readback.
        if presence == "new_container":
            require(container_id is None and resource_id is None and
                    container_ref is None and resource_ref is None,
                    "CREATE_REQUIRES_ABSENT_CONTAINER")
        elif presence == "existing_container":
            require(_positive(container_id) and resource_id is None and
                    container_ref is None and resource_ref is None,
                    "COPY_REQUIRES_EXISTING_PLAN")
        elif presence == "new_item":
            require(resource_id is None and resource_ref is None and
                    ((_positive(container_id) and container_ref is None) or
                     (container_id is None and container_ref is not None)),
                    "CREATE_REQUIRES_EXISTING_CONTAINER_OR_PARENT_REF")
        else:
            require(((_positive(container_id) and container_ref is None) or
                     (container_id is None and container_ref is not None)) and
                    ((_positive(resource_id) and resource_ref is None) or
                     (resource_id is None and resource_ref is not None)),
                    "EXISTING_RESOURCE_ID_REQUIRED")
        before_sha = item["before_sha256"]
        # For a newly created resource the parent inventory snapshot is bound
        # instead of inventing a positive ID for a nonexistent workout/plan.
        require(type(before_sha) is str and SHA.fullmatch(before_sha) is not None,
                "PROVIDER_SNAPSHOT_REQUIRED")
        payload = item["payload"]
        require(type(payload) is dict, "PAYLOAD_REQUIRED")
        _scan_payload(payload)
        require(type(item["depends_on"]) is list and
                all(type(x) is str and TOKEN.fullmatch(x) is not None
                    for x in item["depends_on"]), "DEPENDENCY_INVALID")
        require(len(item["depends_on"]) == len(set(item["depends_on"])) and
                change_id not in item["depends_on"], "DEPENDENCY_INVALID")
        # An independent operation must not silently affect the same object.
        if resource_id is not None or resource_ref is not None:
            identity = (container_kind, container_id, container_ref,
                        resource_id, resource_ref)
            prev = seen_resource.get(identity)
            require(prev is None or prev in item["depends_on"],
                    "SHARED_RESOURCE_REQUIRES_DEPENDENCY")
            seen_resource[identity] = change_id
        normalized.append({
            "id": change_id, "kind": kind, "target": dict(target),
            "payload": payload, "before_sha256": before_sha,
            "depends_on": list(item["depends_on"]),
            "adapter_readiness": KINDS[kind][2],
        })
    # Resolve every symbolic dependency against its producer KIND and its
    # parent scope, not only against a matching string identifier. A child of
    # plan.create/plan.copy never silently lands on the source/last-used plan.
    by_id = {item["id"]: item for item in normalized}
    for child in normalized:
        target = child["target"]
        producer_id = target.get("container_ref")
        if producer_id is not None:
            parent = by_id.get(producer_id)
            require(parent is not None and
                    parent["kind"] in {"plan.create", "plan.copy"} and
                    target["container_kind"] == "training_plan" and
                    producer_id in child["depends_on"],
                    "CONTAINER_REF_MUST_DEPEND_ON_PLAN_CREATE_OR_COPY")
        resource_producer_id = target.get("resource_ref")
        if resource_producer_id is not None:
            producer = by_id.get(resource_producer_id)
            expected_creator = {
                "plan.workout.patch": "plan.workout.create",
                "plan.workout.delete": "plan.workout.create",
                "plan.note.patch": "plan.note.create",
                "plan.note.attachment.add": "plan.note.create",
                "plan.note.attachment.retire": "plan.note.create",
                "library.workout.patch": "library.workout.create",
                "athlete.workout.patch": "athlete.workout.create",
                "athlete.workout.delete": "athlete.workout.create",
            }.get(child["kind"])
            require(producer is not None and expected_creator is not None and
                    producer["kind"] == expected_creator and
                    producer["target"]["container_kind"] == target["container_kind"] and
                    producer["target"]["container_id"] == target["container_id"] and
                    producer["target"].get("container_ref") == producer_id and
                    resource_producer_id in child["depends_on"],
                    "RESOURCE_REF_MUST_MATCH_PARENT_CREATOR")
    graph = {item["id"]: item["depends_on"] for item in normalized}
    require(all(ref in graph for refs in graph.values() for ref in refs),
            "DEPENDENCY_MISSING")
    seen: set[str] = set()
    active: set[str] = set()

    def visit(node: str) -> None:
        require(node not in active, "DEPENDENCY_CYCLE")
        if node in seen:
            return
        active.add(node)
        for dep in graph[node]:
            visit(dep)
        active.remove(node)
        seen.add(node)

    for node in graph:
        visit(node)
    semantic = {"schema": SCHEMA, "owner_id": OWNER, "items": normalized}
    semantic_sha = hashlib.sha256(canonical(semantic).encode()).hexdigest()
    key = request_key or "auto-" + semantic_sha[:36]
    request_id = "ironman-" + hashlib.sha256((str(OWNER) + ":" + key).encode()).hexdigest()[:40]
    draft = {**semantic, "request_id": request_id, "request_key": key,
             "semantic_sha256": semantic_sha, "state": "DRAFT_ONLY",
             "provider_writes": 0, "publication_authorized": False}
    require(len(canonical(draft).encode()) <= MAX_BYTES, "DRAFT_TOO_LARGE")
    return draft


def verify_draft_integrity(draft: dict[str, Any]) -> None:
    """Recompute immutable request identity before any later read/preview.

    A database row, in-memory dictionary or caller-supplied JSON containing
    DRAFT_ONLY is not independently trustworthy. A modified target or payload
    must not inherit the previously checked request identity.
    """
    require(type(draft) is dict and draft.get("schema") == SCHEMA and
            draft.get("state") == "DRAFT_ONLY" and
            draft.get("provider_writes") == 0 and
            draft.get("publication_authorized") is False,
            "DRAFT_NOT_READ_ONLY")
    require(set(draft) == {"schema", "owner_id", "items", "request_id",
                           "request_key", "semantic_sha256", "state",
                           "provider_writes", "publication_authorized"},
            "DRAFT_TAMPERED")
    try:
        reconstructed = prepare_draft([{
            k: v for k, v in item.items() if k != "adapter_readiness"
        } for item in draft["items"]], owner_id=draft["owner_id"],
            request_key=draft["request_key"])
    except (KeyError, TypeError, DraftStop) as exc:
        raise DraftStop("DRAFT_TAMPERED") from exc
    require(draft == reconstructed, "DRAFT_TAMPERED")


class DraftStore:
    """Atomic, 0600 SQLite request persistence on existing Prefect host.

    A request key is stable across chats/retries. A different payload under
    the same key causes a conflict; it never replaces the earlier request.
    """
    def __init__(self, path: Path):
        self.path = Path(path)
        require(self.path.is_absolute() and not self.path.is_symlink() and
                self.path.parent.is_dir() and not self.path.parent.is_symlink(),
                "DRAFT_STORE_PATH_INVALID")
        self.db = sqlite3.connect(str(self.path), timeout=8)
        if os.name == "posix":
            os.chmod(self.path, 0o600)
        self.db.execute("PRAGMA busy_timeout=8000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS drafts (
            request_id TEXT PRIMARY KEY, semantic_sha TEXT NOT NULL,
            payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS previews (
            request_id TEXT NOT NULL, preview_sha TEXT NOT NULL,
            manifest_sha TEXT NOT NULL, manifest_json TEXT NOT NULL,
            result_json TEXT NOT NULL, created_at TEXT NOT NULL
                DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(request_id, preview_sha)
        )""")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def store(self, draft: dict[str, Any]) -> dict[str, Any]:
        verify_draft_integrity(draft)
        body = canonical(draft)
        require(len(body.encode()) <= MAX_BYTES, "DRAFT_TOO_LARGE")
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT semantic_sha, payload FROM drafts WHERE request_id=?",
                                  (draft["request_id"],)).fetchone()
            if row:
                require(row == (draft["semantic_sha256"], body),
                        "REQUEST_ID_REUSED_DIFFERENT_PAYLOAD")
                self.db.commit()
                return {"request_id": draft["request_id"], "reused": True,
                        "state": "DRAFT_ONLY", "provider_writes": 0}
            self.db.execute("INSERT INTO drafts (request_id, semantic_sha, payload) VALUES (?, ?, ?)",
                            (draft["request_id"], draft["semantic_sha256"], body))
            self.db.commit()
            return {"request_id": draft["request_id"], "reused": False,
                    "state": "DRAFT_ONLY", "provider_writes": 0}
        except Exception:
            self.db.rollback()
            raise

    def get(self, request_id: str) -> dict[str, Any] | None:
        require(type(request_id) is str and TOKEN.fullmatch(request_id) is not None,
                "REQUEST_ID_INVALID")
        row = self.db.execute("SELECT semantic_sha, payload FROM drafts WHERE request_id=?",
                              (request_id,)).fetchone()
        if not row:
            return None
        try:
            loaded = json.loads(row[1])
        except (TypeError, ValueError) as exc:
            raise DraftStop("PERSISTED_DRAFT_CORRUPT") from exc
        verify_draft_integrity(loaded)
        require(row[0] == loaded["semantic_sha256"] and
                loaded["request_id"] == request_id,
                "PERSISTED_DRAFT_CORRUPT")
        return loaded

    def store_preview(self, manifest: dict[str, Any],
                      receipt: dict[str, Any]) -> dict[str, Any]:
        """Persist a reviewed, provider-read-only preview independently of execution.

        The request remains immutable; a new preview or a different provider
        observation gets its own SHA. This is never a publish approval.
        """
        from scripts.ironman_jobs.ironman_unified_changeset_engine import (
            digest, validate_manifest,
        )
        manifest_sha = validate_manifest(manifest)
        request_id = manifest["request_id"]
        require(manifest["approval_scope"] == "PREVIEW_ONLY:" + request_id,
                "PREVIEW_SCOPE_REQUIRED")
        require(type(receipt) is dict and
                receipt.get("request_id") == request_id and
                receipt.get("manifest_sha256") == manifest_sha and
                receipt.get("mode") == "preview" and
                receipt.get("request_state") == "PREVIEW_ONLY" and
                receipt.get("provider_writes") == 0 and
                receipt.get("provider_writes_claimed") == 0 and
                receipt.get("publication_enabled") is False,
                "PREVIEW_RECEIPT_NOT_READ_ONLY")
        outcomes = receipt.get("results")
        require(type(outcomes) is list and len(outcomes) == len(manifest["changes"])
                and all(type(row) is dict and row.get("state") in (
                    "PREFLIGHT_PASS", "DONE_VERIFIED",
                ) for row in outcomes) and
                {row.get("id") for row in outcomes} ==
                {item["id"] for item in manifest["changes"]},
                "PREVIEW_NOT_PASSED")
        manifest_json, result_json = canonical(manifest), canonical(receipt)
        preview_sha = hashlib.sha256(
            (manifest_sha + ":" + hashlib.sha256(
                result_json.encode("utf-8")).hexdigest()).encode("ascii")
        ).hexdigest()
        # Match store(): claim the SQLite writer slot BEFORE checking for an
        # existing immutable preview. Two concurrent chats must not race on
        # SELECT-then-INSERT and mistake a duplicate for a new operation.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT semantic_sha,payload FROM drafts WHERE request_id=?",
                (request_id,),
            ).fetchone()
            require(row is not None, "DRAFT_REQUEST_NOT_FOUND")
            stored_draft = json.loads(row[1])
            verify_draft_integrity(stored_draft)
            require(row[0] == stored_draft["semantic_sha256"] and
                    stored_draft["request_id"] == request_id,
                    "PERSISTED_DRAFT_CORRUPT")
            # A forged preview must not inherit a different stored request's
            # identifier. This check is independent of provider readback.
            source_items = stored_draft["items"]
            proposed_items = manifest["changes"]
            require(len(source_items) == len(proposed_items),
                    "PREVIEW_DRAFT_BINDING_MISMATCH")
            for draft_item, proposed in zip(source_items, proposed_items):
                target = draft_item["target"]
                require(
                    proposed["id"] == draft_item["id"] and
                    proposed["kind"] == draft_item["kind"] and
                    proposed["before_sha256"] == draft_item["before_sha256"] and
                    proposed["depends_on"] == draft_item["depends_on"] and
                    proposed["payload"] == draft_item["payload"] and
                    proposed["target"] == {
                        key: target[key] for key in (
                            "provider", "owner_id", "container_kind",
                            "container_id", "resource_id",
                        )
                    },
                    "PREVIEW_DRAFT_BINDING_MISMATCH",
                )
            existing = self.db.execute(
                """SELECT manifest_sha,manifest_json,result_json FROM previews
                   WHERE request_id=? AND preview_sha=?""",
                (request_id, preview_sha),
            ).fetchone()
            if existing:
                require(existing == (manifest_sha, manifest_json, result_json),
                        "PREVIEW_TAMPERED")
                reused = True
            else:
                self.db.execute(
                    """INSERT INTO previews
                       (request_id,preview_sha,manifest_sha,manifest_json,result_json)
                       VALUES (?,?,?,?,?)""",
                    (request_id, preview_sha, manifest_sha, manifest_json, result_json),
                )
                reused = False
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"request_id": request_id, "preview_sha256": preview_sha,
                "reused": reused, "state": "PREVIEW_ONLY",
                "publication_authorized": False, "provider_writes": 0}

    def get_preview(self, request_id: str, preview_sha: str) -> dict[str, Any] | None:
        """Resume a specific immutable preview after a chat rollover."""
        require(type(request_id) is str and TOKEN.fullmatch(request_id) is not None
                and type(preview_sha) is str and SHA.fullmatch(preview_sha) is not None,
                "PREVIEW_LOOKUP_INVALID")
        row = self.db.execute(
            """SELECT manifest_sha,manifest_json,result_json FROM previews
               WHERE request_id=? AND preview_sha=?""",
            (request_id, preview_sha),
        ).fetchone()
        if row is None:
            return None
        manifest_sha, manifest_json, result_json = row
        from scripts.ironman_jobs.ironman_unified_changeset_engine import (
            ChangeStop, digest, validate_manifest,
        )
        try:
            manifest, receipt = json.loads(manifest_json), json.loads(result_json)
            verified_sha = validate_manifest(manifest)
        except (ChangeStop, TypeError, ValueError, KeyError) as exc:
            raise DraftStop("PREVIEW_RECORD_CORRUPT") from exc
        require(verified_sha == manifest_sha and
                hashlib.sha256(
                    (manifest_sha + ":" + hashlib.sha256(
                        result_json.encode("utf-8")).hexdigest()).encode("ascii")
                ).hexdigest() == preview_sha and
                manifest["request_id"] == request_id and
                manifest["approval_scope"] == "PREVIEW_ONLY:" + request_id and
                type(receipt) is dict and
                receipt.get("request_id") == request_id and
                receipt.get("manifest_sha256") == manifest_sha and
                receipt.get("mode") == "preview" and
                receipt.get("request_state") == "PREVIEW_ONLY" and
                receipt.get("provider_writes") == 0 and
                receipt.get("provider_writes_claimed") == 0 and
                receipt.get("publication_enabled") is False,
                "PREVIEW_RECORD_CORRUPT")
        saved_draft = self.get(request_id)
        require(saved_draft is not None, "PREVIEW_ORPHAN_REQUEST")
        source_items, preview_items = saved_draft["items"], manifest["changes"]
        require(len(source_items) == len(preview_items),
                "PREVIEW_RECORD_DRAFT_MISMATCH")
        for source, observed in zip(source_items, preview_items):
            required_target = {
                key: source["target"][key] for key in (
                    "provider", "owner_id", "container_kind",
                    "container_id", "resource_id",
                )
            }
            require(
                observed["id"] == source["id"] and
                observed["kind"] == source["kind"] and
                observed["target"] == required_target and
                observed["payload"] == source["payload"] and
                observed["before_sha256"] == source["before_sha256"] and
                observed["depends_on"] == source["depends_on"],
                "PREVIEW_RECORD_DRAFT_MISMATCH",
            )
        outcomes = receipt.get("results")
        require(type(outcomes) is list and
                len(outcomes) == len(preview_items) and
                all(type(row) is dict and row.get("state") in (
                    "PREFLIGHT_PASS", "DONE_VERIFIED",
                ) for row in outcomes) and
                {row.get("id") for row in outcomes} ==
                {item["id"] for item in preview_items},
                "PREVIEW_RECORD_CORRUPT")
        return {"manifest": manifest, "receipt": receipt,
                "preview_sha256": preview_sha, "publication_authorized": False}


# This is the subset of the EXISTING universal engine that has read-only
# adapters. A prepared request for create/delete is deliberately NOT promoted
# to an executable changeset just because its target was resolved.
PREVIEW_KINDS = frozenset({
    "plan.workout.patch", "plan.note.patch", "plan.note.attachment.add",
    "plan.note.attachment.retire", "plan.strength.relocate",
    "library.workout.patch",
})


def compile_preview_changeset(draft: dict[str, Any],
                              after_images: dict[str, dict[str, Any]],
                              *, pinned_revision: str) -> dict[str, Any]:
    """Build one multi-plan ChangeSetV1 preview with NO per-request Git commit.

    No approval token is produced. Before hashes come from a *freshly
    discovered* provider record at draft creation and are rechecked by the
    existing adapter during preview. Provider writers remain disabled.
    """
    require(type(draft) is dict and draft.get("state") == "DRAFT_ONLY" and
            draft.get("publication_authorized") is False,
            "PREVIEW_DRAFT_REQUIRED")
    verify_draft_integrity(draft)
    require(type(pinned_revision) is str and
            re.fullmatch(r"[a-f0-9]{40}", pinned_revision) is not None,
            "PINNED_REVISION_REQUIRED")
    items = draft.get("items")
    require(type(items) is list and items, "PREVIEW_ITEMS_REQUIRED")
    require(type(after_images) is dict and
            set(after_images) == {x["id"] for x in items},
            "PREVIEW_AFTER_IMAGES_INCOMPLETE")
    converted = []
    for item in items:
        kind = item["kind"]
        require(kind in PREVIEW_KINDS, "PREVIEW_ADAPTER_NOT_RELEASED")
        target = item["target"]
        require(target["container_kind"] in ("training_plan", "workout_library") and
                _positive(target["container_id"]) and
                _positive(target["resource_id"]) and
                target.get("container_ref") is None and
                target.get("resource_ref") is None,
                "PREVIEW_REQUIRES_EXISTING_ITEM")
        image = after_images[item["id"]]
        require(type(image) is dict, "PREVIEW_AFTER_IMAGE_INVALID")
        # A caller must not supply an approved-looking after-image whose SHA
        # differs from the actual desired object the typed adapter would use.
        desired = item["payload"].get("desired")
        if desired is not None:
            require(type(desired) is dict and desired == image,
                    "PREVIEW_PAYLOAD_AFTER_IMAGE_MISMATCH")
        after_sha = hashlib.sha256(canonical(image).encode()).hexdigest()
        require(after_sha != item["before_sha256"], "PREVIEW_NO_CHANGE")
        # Optional symbolic-reference slots may be present as explicit None in
        # a draft, but the original V1 ChangeSet target has EXACTLY five keys.
        # Only actual positive IDs are permitted past the preview boundary.
        concrete_target = {k: target[k] for k in (
            "provider", "owner_id", "container_kind", "container_id", "resource_id"
        )}
        converted.append({
            "id": item["id"], "kind": kind, "target": concrete_target,
            "before_sha256": item["before_sha256"], "after_sha256": after_sha,
            "depends_on": list(item["depends_on"]),
            "payload": item["payload"],
        })
    manifest = {
        "schema": "IRONMAN_CHANGESET_V1",
        "request_id": draft["request_id"], "owner_id": OWNER,
        "reviewed_revision": pinned_revision,
        "approval_scope": "PREVIEW_ONLY:" + draft["request_id"],
        "changes": converted,
    }
    require(len(canonical(manifest).encode()) <= MAX_BYTES, "PREVIEW_TOO_LARGE")
    return {"manifest": manifest, "state": "PREVIEW_ONLY",
            "provider_writes": 0, "publication_authorized": False}
