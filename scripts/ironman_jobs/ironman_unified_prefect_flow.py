"""ONE Prefect entrypoint for generic IRONMAN plan/library changesets.

Stage 1: provider-backed preview with all six resource categories. Execution
of provider writes is disabled until each reusable writer adapter has been
reviewed and canaried via the canonical Proven Paths process.

Prefect owns flow/task history; the SQLite ledger owns item-level receipts.
Do not duplicate either for an individual plan, workout or attachment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from prefect import flow, task

from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    ChangeStop, Ledger, validate_manifest, run_changeset,
)
from scripts.ironman_jobs.ironman_unified_trainingpeaks_reads import (
    create_read_registry,
)
from scripts.ironman_jobs.ironman_dynamic_request_store import (
    DraftStore, prepare_draft, compile_preview_changeset,
)

MAX_MANIFEST_BYTES = 2_000_000

def require_requested_targets(manifest: dict[str, Any],
                              requested_targets: list[dict[str, Any]] | None) -> None:
    """Bind the independent user-confirmed targets before any provider/ledger IO.

    Never use the previous manifest as the request selector: the caller must
    supply the resource identities resolved from the current request.
    This is one generic guard for every plan, workout, note, PDF and Library.
    """
    if type(requested_targets) is not list or not requested_targets:
        raise ChangeStop("REQUEST_TARGET_BINDING_REQUIRED")
    if len(requested_targets) > 1000:
        raise ChangeStop("REQUEST_TARGET_BINDING_LIMIT")
    expected = set()
    for entry in requested_targets:
        if type(entry) is not dict or set(entry) != {"kind", "target"}:
            raise ChangeStop("REQUEST_TARGET_BINDING_SHAPE")
        kind, target = entry["kind"], entry["target"]
        if type(kind) is not str or type(target) is not dict or set(target) != {
            "provider", "owner_id", "container_kind", "container_id", "resource_id"
        }:
            raise ChangeStop("REQUEST_TARGET_BINDING_SHAPE")
        if (target["provider"] != "trainingpeaks"
                or type(target["owner_id"]) is not int
                or target["owner_id"] != manifest["owner_id"]
                or target["container_kind"] not in ("training_plan", "workout_library")
                or any(type(target[k]) is not int or target[k] <= 0
                       for k in ("container_id", "resource_id"))):
            raise ChangeStop("REQUEST_TARGET_BINDING_INVALID")
        key = (kind, target["provider"], target["owner_id"],
               target["container_kind"], target["container_id"],
               target["resource_id"])
        if key in expected:
            raise ChangeStop("REQUEST_TARGET_BINDING_DUPLICATE")
        expected.add(key)
    actual = {(i["kind"], i["target"]["provider"], i["target"]["owner_id"],
               i["target"]["container_kind"], i["target"]["container_id"],
               i["target"]["resource_id"]) for i in manifest["changes"]}
    if expected != actual:
        raise ChangeStop("STOP_TARGET_MISMATCH")


@task(name="validate-one-ironman-changeset", retries=0, persist_result=False,
      log_prints=False)
def validate_change_request(manifest: dict[str, Any]) -> str:
    return validate_manifest(manifest)


@task(name="preview-one-ironman-changeset", retries=0, persist_result=False,
      log_prints=False)
def preview_change_request(manifest: dict[str, Any],
                           ledger_path: str,
                           read_transport: str = "local") -> dict[str, Any]:
    path = Path(ledger_path)
    if not path.is_absolute() or path.is_symlink():
        raise ChangeStop("LEDGER_PATH_NOT_ABSOLUTE_OR_SYMLINK")
    if not path.parent.is_dir():
        raise ChangeStop("LEDGER_PARENT_NOT_READY")
    # Read the actual provider object via an allowlisted resource adapter.
    # All adapters are READ-ONLY; there is no provider mutation here.
    # Preview is read-only and must not reserve the durable execution identity.
    # Each preview gets an isolated SQLite ledger; the persistent request store
    # remains the sole source of request identity across chats.
    ledger = Ledger(Path(":memory:"))
    try:
        result = run_changeset(
            manifest, create_read_registry(read_transport), ledger, execute=False,
        )
    finally:
        ledger.close()
    result["provider_writes"] = 0
    result["publication_enabled"] = False
    result["source"] = "trainingpeaks_live_read_only"
    return result


@flow(name="ironman-unified-changeset-v1", retries=0,
      log_prints=False, persist_result=False)
def unified_changeset_flow(
    manifest: dict[str, Any],
    ledger_path: str,
    *,
    mode: str = "preview",
    read_transport: str = "local",
    requested_targets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One generic flow: any plan/library resource type and any target ID.

    NOTE: this deployment is preview-only, not a hidden alternate publishing
    route. A separate reviewed release may enable normal approved writers.
    """
    # One shared flow now accepts an operation draft from any authorized chat.
    # This prepares a persistent request only. It NEVER reads/writes provider
    # data, declares approval, or selects targets from a previous manifest.
    if mode == "prepare":
        if type(manifest) is not dict or set(manifest) not in (
            {"schema", "items"}, {"schema", "items", "request_key"}
        ) or manifest.get("schema") != "IRONMAN_OPERATION_INPUT_V1":
            raise ChangeStop("OPERATION_INPUT_SHAPE")
        store_path = os.environ.get("IRONMAN_OPERATION_DRAFT_STORE")
        if not store_path:
            raise ChangeStop("DRAFT_STORE_NOT_CONFIGURED")
        draft = prepare_draft(
            manifest["items"], request_key=manifest.get("request_key"),
        )
        store = DraftStore(Path(store_path))
        try:
            receipt = store.store(draft)
        finally:
            store.close()
        return {
            **receipt, "adapter_readiness": {
                item["id"]: item["adapter_readiness"] for item in draft["items"]
            },
            "publication_enabled": False, "source": "request_draft_local_only",
        }
    if mode == "preview_draft":
        # A stored operation request is NOT an authorization. Re-read it from
        # the private request store, verify its content hash and bind a second,
        # independent current-request target list before any provider I/O.
        if read_transport not in {"local", "private_bridge"}:
            raise ChangeStop("UNIFIED_UNSUPPORTED_READ_TRANSPORT")
        if type(manifest) is not dict or set(manifest) != {
            "schema", "request_id", "after_images", "pinned_revision"
        } or manifest.get("schema") != "IRONMAN_DRAFT_PREVIEW_INPUT_V1":
            raise ChangeStop("DRAFT_PREVIEW_INPUT_SHAPE")
        store_path = os.environ.get("IRONMAN_OPERATION_DRAFT_STORE")
        if not store_path:
            raise ChangeStop("DRAFT_STORE_NOT_CONFIGURED")
        store = DraftStore(Path(store_path))
        try:
            draft = store.get(manifest["request_id"])
        finally:
            store.close()
        if draft is None:
            raise ChangeStop("DRAFT_REQUEST_NOT_FOUND")
        compiled = compile_preview_changeset(
            draft, manifest["after_images"],
            pinned_revision=manifest["pinned_revision"],
        )
        preview_manifest = compiled["manifest"]
        validate_change_request(preview_manifest)
        require_requested_targets(preview_manifest, requested_targets)
        result = preview_change_request(preview_manifest, ledger_path, read_transport)
        result["request_id"] = draft["request_id"]
        result["approval_scope"] = preview_manifest["approval_scope"]
        result["publication_enabled"] = False
        result["provider_writes"] = 0
        # A passing provider-read preview is durable across chat restarts.
        # This is a separate immutable snapshot, not an execution receipt or
        # implicit approval. A failed preflight is returned but not promoted.
        if all(row.get("state") in ("PREFLIGHT_PASS", "DONE_VERIFIED")
               for row in result.get("results", [])):
            store = DraftStore(Path(store_path))
            try:
                preview_receipt = store.store_preview(preview_manifest, result)
            finally:
                store.close()
            result["preview_sha256"] = preview_receipt["preview_sha256"]
            result["preview_reused"] = preview_receipt["reused"]
            result["preview_persisted"] = True
        else:
            result["preview_persisted"] = False
        return result
    if mode != "preview":
        raise ChangeStop("PUBLISHING_NOT_YET_ENABLED_FOR_UNIFIED_FLOW")
    if read_transport not in {"local", "private_bridge"}:
        raise ChangeStop("UNIFIED_UNSUPPORTED_READ_TRANSPORT")
    validate_change_request(manifest)
    require_requested_targets(manifest, requested_targets)
    return preview_change_request(manifest, ledger_path, read_transport)


def load_manifest(path: Path) -> dict[str, Any]:
    """Offline source parser. No arbitrary URL, Python code or shell commands."""
    if not path.is_file() or path.is_symlink():
        raise ChangeStop("MANIFEST_SOURCE_NOT_REGULAR_FILE")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ChangeStop("MANIFEST_TOO_LARGE")
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest(data)
    return data
