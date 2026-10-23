"""ONE Prefect entrypoint for generic IRONMAN plan/library changesets.

Stage 1: provider-backed preview with all six resource categories. Execution
of provider writes is disabled until each reusable writer adapter has been
reviewed and canaried via the canonical Proven Paths process.

Prefect owns flow/task history; the SQLite ledger owns item-level receipts.
Do not duplicate either for an individual plan, workout or attachment.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prefect import flow, task

from scripts.ironman_jobs.ironman_unified_changeset_engine import (
    ChangeStop, Ledger, validate_manifest, run_changeset,
)
from scripts.ironman_jobs.ironman_unified_trainingpeaks_reads import (
    create_read_registry,
)

MAX_MANIFEST_BYTES = 2_000_000


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
    ledger = Ledger(path)
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
) -> dict[str, Any]:
    """One generic flow: any plan/library resource type and any target ID.

    NOTE: this deployment is preview-only, not a hidden alternate publishing
    route. A separate reviewed release may enable normal approved writers.
    """
    if mode != "preview":
        raise ChangeStop("PUBLISHING_NOT_YET_ENABLED_FOR_UNIFIED_FLOW")
    if read_transport not in {"local", "private_bridge"}:
        raise ChangeStop("UNIFIED_UNSUPPORTED_READ_TRANSPORT")
    validate_change_request(manifest)
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
