"""Private source-routing configuration for Coaching Radar canonical Drive context.

The repository contains only the validator/loader. Actual Google Drive document IDs
belong in a root/service-user-only JSON file on the Prefect host.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.ironman_jobs.coaching_radar_drive_context_adapter_v0 import ContextDocumentSpec
from scripts.ironman_jobs.coaching_radar_kb_context_v0 import REQUIRED_ROLES

SCHEMA = "IRONMAN_RADAR_CONTEXT_SOURCES_V1"
GLOBAL_ROLES = (
    "core_index",
    "master_coaching_context",
    "decision_log",
    "open_questions_roadmap",
    "workstream_state",
)


def _spec(raw: Any, role: str) -> ContextDocumentSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"KB_SOURCE_SPEC_MISSING:{role}")
    document_id = str(raw.get("document_id") or "").strip()
    expected_title = str(raw.get("expected_title") or "").strip()
    if not document_id or not expected_title:
        raise ValueError(f"KB_SOURCE_SPEC_INVALID:{role}")
    return ContextDocumentSpec(role=role, document_id=document_id, expected_title=expected_title)


def load_private_source_config(
    path: str | Path,
    *,
    active_athlete_ids: set[int],
) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_file():
        raise RuntimeError("KB_SOURCE_CONFIG_MISSING")
    mode = config_path.stat().st_mode & 0o777
    if mode & 0o077:
        raise RuntimeError(f"KB_SOURCE_CONFIG_PERMISSIONS_TOO_OPEN:{oct(mode)}")

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if raw.get("schema") != SCHEMA:
        raise ValueError("KB_SOURCE_CONFIG_SCHEMA_MISMATCH")

    global_raw = raw.get("global_documents")
    if not isinstance(global_raw, dict):
        raise ValueError("KB_SOURCE_GLOBAL_DOCUMENTS_MISSING")
    global_specs = {role: _spec(global_raw.get(role), role) for role in GLOBAL_ROLES}

    specialist_raw = raw.get("specialist_documents")
    if not isinstance(specialist_raw, list) or not specialist_raw:
        raise ValueError("KB_SOURCE_SPECIALISTS_MISSING")
    specialist_specs = [
        _spec(item, f"specialist:{index}") for index, item in enumerate(specialist_raw)
    ]

    athlete_raw = raw.get("athletes")
    if not isinstance(athlete_raw, dict):
        raise ValueError("KB_SOURCE_ATHLETES_MISSING")
    configured_ids = {int(value) for value in athlete_raw}
    if configured_ids != {int(value) for value in active_athlete_ids}:
        missing = sorted(active_athlete_ids - configured_ids)
        extra = sorted(configured_ids - active_athlete_ids)
        raise ValueError(f"KB_SOURCE_ROSTER_MISMATCH:missing={missing}:extra={extra}")

    athlete_cards: dict[int, ContextDocumentSpec] = {}
    for athlete_id in sorted(configured_ids):
        athlete_cards[athlete_id] = _spec(
            athlete_raw[str(athlete_id)].get("athlete_card"),
            "athlete_card",
        )

    return {
        "global_documents": global_specs,
        "specialist_documents": specialist_specs,
        "athlete_cards": athlete_cards,
    }


def context_specs_for_athlete(
    loaded: dict[str, Any],
    *,
    athlete_id: int,
) -> tuple[dict[str, ContextDocumentSpec], list[ContextDocumentSpec]]:
    athlete_cards = loaded["athlete_cards"]
    if int(athlete_id) not in athlete_cards:
        raise ValueError("KB_SOURCE_ATHLETE_NOT_CONFIGURED")
    global_specs = dict(loaded["global_documents"])
    documents = {
        "core_index": global_specs["core_index"],
        "master_coaching_context": global_specs["master_coaching_context"],
        "decision_log": global_specs["decision_log"],
        "open_questions_roadmap": global_specs["open_questions_roadmap"],
        "athlete_card": athlete_cards[int(athlete_id)],
        "workstream_state": global_specs["workstream_state"],
    }
    if set(documents) != set(REQUIRED_ROLES):
        raise RuntimeError("KB_SOURCE_REQUIRED_ROLE_INTERNAL_MISMATCH")
    return documents, list(loaded["specialist_documents"])
