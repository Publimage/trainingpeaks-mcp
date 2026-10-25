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
        require(type(target) is dict and set(target) == {
            "provider", "owner_id", "container_kind", "container_id", "resource_id",
        }, "TARGET_FIELDS")
        require(target["provider"] == "trainingpeaks" and
                type(target["owner_id"]) is int and target["owner_id"] == OWNER and
                target["container_kind"] == container_kind, "TARGET_MISMATCH")
        container_id, resource_id = target["container_id"], target["resource_id"]
        if presence == "new_container":
            require(container_id is None and resource_id is None,
                    "CREATE_REQUIRES_ABSENT_CONTAINER")
        elif presence == "existing_container":
            require(_positive(container_id) and resource_id is None,
                    "COPY_REQUIRES_EXISTING_PLAN")
        elif presence == "new_item":
            require(_positive(container_id) and resource_id is None,
                    "CREATE_REQUIRES_EXISTING_CONTAINER")
        else:
            require(_positive(container_id) and _positive(resource_id),
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
        if resource_id is not None:
            identity = (container_kind, container_id, resource_id)
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
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def store(self, draft: dict[str, Any]) -> dict[str, Any]:
        require(type(draft) is dict and draft.get("schema") == SCHEMA and
                draft.get("state") == "DRAFT_ONLY" and
                draft.get("provider_writes") == 0 and
                draft.get("publication_authorized") is False,
                "DRAFT_NOT_READ_ONLY")
        try:
            reconstructed = prepare_draft([{
                k: v for k, v in item.items() if k != "adapter_readiness"
            } for item in draft["items"]],
                owner_id=draft["owner_id"], request_key=draft["request_key"])
        except (KeyError, TypeError, DraftStop) as exc:
            raise DraftStop("DRAFT_TAMPERED") from exc
        require(draft == reconstructed, "DRAFT_TAMPERED")
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
        row = self.db.execute("SELECT payload FROM drafts WHERE request_id=?",
                              (request_id,)).fetchone()
        return json.loads(row[0]) if row else None
